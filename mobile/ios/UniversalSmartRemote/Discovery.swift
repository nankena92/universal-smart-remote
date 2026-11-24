import Foundation

/// TV discovery for the SmartRemoteNative bridge (CONTRACTS.md §3).
///
/// Two mechanisms, mirroring the Android module (Phase 2) where possible:
/// 1. Bonjour (primary on iOS): `NetServiceBrowser` for `_googlecast._tcp`,
///    `_airplay._tcp` and `_http._tcp`, resolving each service to an IPv4
///    address + port. Brand is derived best-effort from the service name
///    and TXT record; `"unknown"` when it cannot be determined.
/// 2. SSDP (best-effort): M-SEARCH over UDP multicast to 239.255.255.250:1900
///    with BSD sockets, parsing LOCATION / USN / SERVER headers and fetching
///    the UPnP device description XML for a friendly name, exactly like the
///    Android module. NOTE: on iOS 14+ sending/receiving IP multicast
///    requires the "Multicast Networking" entitlement
///    (`com.apple.developer.networking.multicast`), which Apple grants only
///    on request. Without it the SSDP socket cannot join the group and SSDP
///    silently finds nothing — Bonjour keeps working, and the failure is
///    logged, never faked. See ios/README.md.
///
/// Local Network permission (iOS 14+): the first Bonjour browse triggers
/// the system prompt. If the user denies access, the browser fails via
/// `netServiceBrowser(_:didNotSearch:)` and `onBrowserFailed` fires with a
/// clear message telling the user to enable Local Network in Settings.
/// Discovery results are never invented.
///
/// All mutable state lives on the main queue: `NetServiceBrowser` and
/// `NetService` must be driven from a run loop, so Bonjour work happens on
/// the main thread, and the SSDP read source hops to the main queue before
/// touching shared state. `start()` / `stop()` are safe to call from any
/// thread.
///
/// NEEDS ON-DEVICE VERIFICATION: no Mac/Xcode was available when this was
/// written, so Bonjour resolution, the SSDP socket flow and the denied-
/// permission path have not been run on a real iPhone.
final class TvDiscovery: NSObject {

    // MARK: - Callbacks (invoked on the main queue)

    /// A TV was found. Payload is a `DiscoveredTv` dictionary:
    /// `{name, brand, model, ip, port, mac, source}` (`mac` is NSNull when
    /// the discovery source carries no MAC address).
    var onTvFound: (([String: Any]) -> Void)?

    /// A Bonjour browse failed — in practice this means Local Network
    /// access was denied or is unavailable. Message is user-facing.
    var onBrowserFailed: ((String) -> Void)?

    // MARK: - Bonjour

    private static let bonjourTypes = ["_googlecast._tcp.", "_airplay._tcp.", "_http._tcp."]
    private var browsers: [NetServiceBrowser] = []
    private var resolvingServices: [NetService] = []
    private var seenBonjourKeys = Set<String>()

    // MARK: - SSDP

    private static let ssdpAddress = "239.255.255.250"
    private static let ssdpPort: UInt16 = 1900
    private static let ssdpResendInterval: TimeInterval = 4.0
    /// ST values probed on every M-SEARCH round (generic + targeted),
    /// mirroring the Android module.
    private static let searchTargets = [
        "ssdp:all",
        "upnp:rootdevice",
        "urn:samsung.com:device:RemoteControlReceiver:1",
        "urn:dial-multiscreen-org:service:dial:1",
    ]
    private let ssdpQueue = DispatchQueue(label: "com.universalremote.discovery-ssdp")
    private var ssdpSocket: Int32 = -1
    private var ssdpReadSource: DispatchSourceRead?
    private var ssdpTimer: DispatchSourceTimer?
    private var seenSsdpKeys = Set<String>()

    private(set) var isDiscovering = false

    // MARK: - Start / stop

    func start() {
        DispatchQueue.main.async { [weak self] in
            guard let self = self, !self.isDiscovering else { return }
            self.isDiscovering = true
            self.seenBonjourKeys.removeAll()
            self.seenSsdpKeys.removeAll()
            self.startBonjour()
            self.startSsdp()
        }
    }

    func stop() {
        DispatchQueue.main.async { [weak self] in
            guard let self = self, self.isDiscovering else { return }
            self.isDiscovering = false
            self.stopBonjour()
            self.stopSsdp()
        }
    }

    // MARK: - Bonjour

    private func startBonjour() {
        // Must run on the main thread: NetServiceBrowser delivers its
        // delegate callbacks on the run loop of the thread that started it.
        for type in Self.bonjourTypes {
            let browser = NetServiceBrowser()
            browser.delegate = self
            browsers.append(browser)
            browser.searchForServices(ofType: type, inDomain: "local.")
        }
    }

    private func stopBonjour() {
        for browser in browsers {
            browser.stop()
            browser.delegate = nil
        }
        browsers.removeAll()
        for service in resolvingServices {
            service.stop()
            service.delegate = nil
        }
        resolvingServices.removeAll()
    }

    private func tvDictionary(fromResolvedService service: NetService) -> [String: Any]? {
        var ipAddress: String?
        for data in service.addresses ?? [] {
            if let found = Self.ipv4Address(from: data) {
                ipAddress = found
                break
            }
        }
        // The bridge contract carries an IPv4 `ip`; IPv6-only services are
        // skipped rather than reported with an unusable address.
        guard let ip = ipAddress else { return nil }

        let txt = NetService.dictionary(fromTXTRecord: service.txtRecordData() ?? Data())
        var txtStrings: [String: String] = [:]
        for (key, value) in txt {
            txtStrings[key.lowercased()] = String(data: value, encoding: .utf8) ?? ""
        }

        let brand = Self.brandForBonjour(type: service.type, name: service.name, txt: txtStrings)
        let model = txtStrings["md"] ?? txtStrings["model"] ?? ""
        return [
            "name": service.name.isEmpty ? Self.friendlyName(for: brand) : service.name,
            "brand": brand,
            "model": model,
            "ip": ip,
            "port": service.port,
            "mac": Self.macFromAirPlayDeviceId(txtStrings["deviceid"]) ?? NSNull(),
            "source": "bonjour",
        ]
    }

    /// Best-effort brand from the Bonjour service type, name and TXT
    /// record. Returns `"unknown"` when nothing matches (CONTRACTS.md §2).
    /// A bare Cast receiver with no recognisable model is `"unknown"` — a
    /// Chromecast dongle is not an Android TV, and guessing would send the
    /// connect flow down the wrong adapter.
    private static func brandForBonjour(type: String, name: String, txt: [String: String]) -> String {
        let haystack = [name, txt["md"] ?? "", txt["model"] ?? "", txt["fn"] ?? ""]
            .joined(separator: " ").lowercased()
        if haystack.contains("samsung") { return "samsung" }
        if haystack.contains("roku") { return "roku" }
        if haystack.contains("lg") || haystack.contains("webos") { return "lg" }
        if haystack.contains("sony") || haystack.contains("bravia") { return "sony" }
        if haystack.contains("tcl") { return "tcl" }
        if type.contains("_airplay") {
            // Apple TV / AirPlay speakers: no adapter for these in this
            // project, and AirPlay alone does not identify the TV brand.
            return "unknown"
        }
        if type.contains("_googlecast") {
            if haystack.contains("google tv") { return "googletv" }
            if haystack.contains("android tv") { return "androidtv" }
            return "unknown"
        }
        return "unknown"
    }

    /// AirPlay's `deviceid` TXT value is usually the device MAC address
    /// ("AA:BB:CC:DD:EE:FF"). Only used when it is shaped like a MAC;
    /// anything else (UUIDs, opaque ids) is ignored.
    private static func macFromAirPlayDeviceId(_ deviceId: String?) -> String? {
        guard let id = deviceId, !id.isEmpty else { return nil }
        guard id.range(of: "^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$",
                       options: .regularExpression) != nil else { return nil }
        return id.uppercased()
    }

    private static func ipv4Address(from data: Data) -> String? {
        guard data.count >= MemoryLayout<sockaddr_in>.size else { return nil }
        return data.withUnsafeBytes { raw -> String? in
            guard let base = raw.baseAddress else { return nil }
            let sockaddrPtr = base.assumingMemoryBound(to: sockaddr.self)
            guard sockaddrPtr.pointee.sa_family == sa_family_t(AF_INET) else { return nil }
            var addr = base.assumingMemoryBound(to: sockaddr_in.self).pointee.sin_addr
            var buffer = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
            guard inet_ntop(AF_INET, &addr, &buffer, socklen_t(INET_ADDRSTRLEN)) != nil else {
                return nil
            }
            return String(cString: buffer)
        }
    }

    // MARK: - SSDP

    private func startSsdp() {
        guard let fd = makeSsdpSocket() else {
            // Non-fatal: Bonjour is the primary path on iOS (see header).
            NSLog("[SmartRemoteNative] SSDP unavailable (socket setup failed); continuing with Bonjour only.")
            return
        }
        ssdpSocket = fd

        let readSource = DispatchSource.makeReadSource(fileDescriptor: fd, queue: ssdpQueue)
        readSource.setEventHandler { [weak self] in
            self?.drainSsdpSocket(fd)
        }
        // The cancel handler owns closing the fd: it runs after any
        // in-flight read handler, so the fd is never closed mid-recvfrom.
        readSource.setCancelHandler { close(fd) }
        ssdpReadSource = readSource
        readSource.resume()

        sendMSearch(fd)
        let timer = DispatchSource.makeTimerSource(queue: ssdpQueue)
        timer.schedule(deadline: .now() + Self.ssdpResendInterval, repeating: Self.ssdpResendInterval)
        timer.setEventHandler { [weak self] in
            // The timer is cancelled in stopSsdp; a single in-flight fire
            // after close is harmless (sendto on a closed fd just fails).
            guard let self = self else { return }
            self.sendMSearch(fd)
        }
        ssdpTimer = timer
        timer.resume()
    }

    private func stopSsdp() {
        ssdpTimer?.cancel()
        ssdpTimer = nil
        ssdpReadSource?.cancel()
        ssdpReadSource = nil
        ssdpSocket = -1
    }

    private func makeSsdpSocket() -> Int32? {
        let fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        guard fd >= 0 else { return nil }

        var reuse: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, socklen_t(MemoryLayout<Int32>.size))

        // Non-blocking, so the drain loop below can stop at EWOULDBLOCK.
        let flags = fcntl(fd, F_GETFL)
        if flags >= 0 {
            _ = fcntl(fd, F_SETFL, flags | O_NONBLOCK)
        }

        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = UInt16(Self.ssdpPort).bigEndian
        addr.sin_addr = in_addr(s_addr: INADDR_ANY)
        let bound = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard bound == 0 else {
            close(fd)
            return nil
        }

        var mreq = ip_mreq()
        mreq.imr_multiaddr.s_addr = inet_addr(Self.ssdpAddress)
        mreq.imr_interface.s_addr = INADDR_ANY
        if setsockopt(fd, IPPROTO_IP, IP_ADD_MEMBERSHIP,
                      &mreq, socklen_t(MemoryLayout<ip_mreq>.size)) != 0 {
            // Without the multicast entitlement iOS refuses the group join;
            // unicast M-SEARCH replies can still arrive, so keep the socket.
            NSLog("[SmartRemoteNative] Could not join SSDP multicast group (errno %d); SSDP replies may be limited.", errno)
        }
        return fd
    }

    private func sendMSearch(_ fd: Int32) {
        var dest = sockaddr_in()
        dest.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        dest.sin_family = sa_family_t(AF_INET)
        dest.sin_port = UInt16(Self.ssdpPort).bigEndian
        dest.sin_addr.s_addr = inet_addr(Self.ssdpAddress)
        for st in Self.searchTargets {
            let request = "M-SEARCH * HTTP/1.1\r\n"
                + "HOST: \(Self.ssdpAddress):\(Self.ssdpPort)\r\n"
                + "MAN: \"ns=01\"\r\n"
                + "MX: 3\r\n"
                + "ST: \(st)\r\n"
                + "USER-AGENT: UniversalSmartRemote/1.0 UPnP/1.0\r\n"
                + "\r\n"
            guard let data = request.data(using: .utf8) else { continue }
            data.withUnsafeBytes { raw in
                withUnsafePointer(to: &dest) {
                    $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                        _ = sendto(fd, raw.baseAddress, data.count, 0,
                                   $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                    }
                }
            }
        }
    }

    /// Drains every pending datagram, then hops to the main queue to parse.
    /// Runs on `ssdpQueue`; the socket is non-blocking so the loop ends at
    /// EWOULDBLOCK instead of blocking the queue.
    private func drainSsdpSocket(_ fd: Int32) {
        var buffer = [UInt8](repeating: 0, count: 8192)
        while true {
            var srcAddr = sockaddr_storage()
            var srcLen = socklen_t(MemoryLayout<sockaddr_storage>.size)
            let received = withUnsafeMutablePointer(to: &srcAddr) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    recvfrom(fd, &buffer, buffer.count, 0, $0, &srcLen)
                }
            }
            guard received > 0 else { return }
            let text = String(bytes: buffer[0..<received], encoding: .utf8) ?? ""
            var senderIp: String?
            if srcAddr.ss_family == sa_family_t(AF_INET) {
                let sin = withUnsafePointer(to: &srcAddr) {
                    $0.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { $0.pointee }
                }
                var addr = sin.sin_addr
                var ipBuffer = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
                if inet_ntop(AF_INET, &addr, &ipBuffer, socklen_t(INET_ADDRSTRLEN)) != nil {
                    senderIp = String(cString: ipBuffer)
                }
            }
            let payload = text
            DispatchQueue.main.async { [weak self] in
                self?.handleSsdpResponse(payload, senderIp: senderIp)
            }
        }
    }

    /// Parses one SSDP response (main queue). Mirrors the Android module:
    /// LOCATION gives ip/port, SERVER/USN/ST give the brand, and the UPnP
    /// description XML gives the friendly name / model (best effort).
    private func handleSsdpResponse(_ text: String, senderIp: String?) {
        guard isDiscovering else { return }
        var headers: [String: String] = [:]
        for line in text.components(separatedBy: "\r\n").dropFirst() {
            guard let colon = line.firstIndex(of: ":") else { continue }
            let key = line[..<colon].trimmingCharacters(in: .whitespaces).lowercased()
            let value = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
            headers[key] = value
        }
        let location = headers["location"]
        let usn = headers["usn"]
        let st = headers["st"]
        let server = headers["server"]

        // LOCATION is the device description URL; fall back to the sender's
        // address when a device answers without one.
        var ip = senderIp
        var port = 80
        if let location = location, let url = URL(string: location), let host = url.host {
            ip = host
            if let urlPort = url.port {
                port = urlPort
            } else {
                port = url.scheme?.lowercased() == "https" ? 443 : 80
            }
        }
        guard let ipAddress = ip, !ipAddress.isEmpty else { return }

        // Dedupe key matches Android: ip + USN (or ST when USN is absent).
        let dedupeKey = ipAddress + "|" + (usn ?? st ?? "")
        guard seenSsdpKeys.insert(dedupeKey).inserted else { return }

        let brand = Self.brandForSsdp(server: server, usn: usn, st: st)
        if let location = location {
            fetchDescription(location: location) { [weak self] name, model in
                DispatchQueue.main.async {
                    guard let self = self, self.isDiscovering else { return }
                    self.emitSsdpTv(name: name ?? Self.friendlyName(for: brand),
                                    brand: brand, model: model ?? "",
                                    ip: ipAddress, port: port)
                }
            }
        } else {
            emitSsdpTv(name: Self.friendlyName(for: brand), brand: brand,
                       model: "", ip: ipAddress, port: port)
        }
    }

    private func emitSsdpTv(name: String, brand: String, model: String, ip: String, port: Int) {
        onTvFound?([
            "name": name,
            "brand": brand,
            "model": model,
            "ip": ip,
            "port": port,
            // SSDP carries no MAC address; null is honest. (Same as Android.)
            "mac": NSNull(),
            "source": "ssdp",
        ])
    }

    /// Best-effort brand detection from SERVER / USN / ST headers.
    /// Returns `"unknown"` when nothing matches (CONTRACTS.md §2).
    private static func brandForSsdp(server: String?, usn: String?, st: String?) -> String {
        let haystack = [server ?? "", usn ?? "", st ?? ""]
            .joined(separator: " ").lowercased()
        if haystack.contains("samsung") { return "samsung" }
        if haystack.contains("roku") { return "roku" }
        if haystack.contains("lg") || haystack.contains("webos") { return "lg" }
        if haystack.contains("sony") || haystack.contains("bravia") { return "sony" }
        if haystack.contains("tcl") { return "tcl" }
        if haystack.contains("android") || haystack.contains("google")
            || haystack.contains("chromecast") { return "androidtv" }
        return "unknown"
    }

    /// Fetches the UPnP device description XML at the LOCATION URL and
    /// extracts friendlyName / modelName. Time-boxed; any failure yields
    /// (nil, nil) rather than blocking discovery.
    private func fetchDescription(location: String,
                                  completion: @escaping (String?, String?) -> Void) {
        guard let url = URL(string: location) else {
            completion(nil, nil)
            return
        }
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 2.0
        config.timeoutIntervalForResource = 2.0
        let session = URLSession(configuration: config)
        let task = session.dataTask(with: url) { data, response, _ in
            defer { session.finishTasksAndInvalidate() }
            guard let data = data,
                  let http = response as? HTTPURLResponse, http.statusCode == 200,
                  let xml = String(data: data, encoding: .utf8) else {
                completion(nil, nil)
                return
            }
            completion(Self.extractXmlTag(xml, tag: "friendlyName"),
                       Self.extractXmlTag(xml, tag: "modelName"))
        }
        task.resume()
    }

    private static func extractXmlTag(_ xml: String, tag: String) -> String? {
        guard let open = xml.range(of: "<\(tag)>"),
              let close = xml.range(of: "</\(tag)>", range: open.upperBound..<xml.endIndex) else {
            return nil
        }
        let value = xml[open.upperBound..<close.lowerBound]
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }

    private static func friendlyName(for brand: String) -> String {
        switch brand {
        case "samsung": return "Samsung TV"
        case "roku": return "Roku TV"
        case "lg": return "LG TV"
        case "sony": return "Sony TV"
        case "tcl": return "TCL TV"
        case "androidtv": return "Android TV"
        case "googletv": return "Google TV"
        default: return "Unknown TV"
        }
    }
}

// MARK: - NetServiceBrowserDelegate / NetServiceDelegate

extension TvDiscovery: NetServiceBrowserDelegate {

    func netServiceBrowser(_ browser: NetServiceBrowser,
                           didFind service: NetService,
                           moreComing: Bool) {
        let key = "\(service.type)|\(service.name)"
        guard seenBonjourKeys.insert(key).inserted else { return }
        // The service must be retained while resolving; it is released in
        // netServiceDidResolveAddress / netService(_:didNotResolve:).
        resolvingServices.append(service)
        service.delegate = self
        service.resolve(withTimeout: 8.0)
    }

    func netServiceBrowser(_ browser: NetServiceBrowser,
                           didNotSearch errorDict: [String: NSNumber]) {
        let code = errorDict[NSNetServicesErrorCode]?.intValue ?? -1
        let message = "Local network access was denied or is unavailable "
            + "(NetServices error \(code)). Enable Local Network for "
            + "Universal Smart Remote in iOS Settings → Privacy & Security → "
            + "Local Network, then try discovering again."
        stop()
        onBrowserFailed?(message)
    }

    func netServiceBrowser(_ browser: NetServiceBrowser,
                           didRemove service: NetService,
                           moreComing: Bool) {
        // No removal event exists in the bridge contract; ignored.
    }
}

extension TvDiscovery: NetServiceDelegate {

    func netServiceDidResolveAddress(_ sender: NetService) {
        resolvingServices.removeAll { $0 === sender }
        guard let tv = tvDictionary(fromResolvedService: sender) else { return }
        onTvFound?(tv)
    }

    func netService(_ sender: NetService, didNotResolve errorDict: [String: NSNumber]) {
        resolvingServices.removeAll { $0 === sender }
        // Non-fatal: one service failing to resolve must not kill discovery.
    }
}
