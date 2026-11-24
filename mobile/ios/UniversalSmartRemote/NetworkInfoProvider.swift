import Foundation
import Network
import NetworkExtension
import SystemConfiguration

/// Reads the phone's network state for the SmartRemoteNative bridge
/// (CONTRACTS.md §3 `getNetworkInfo` / `isWifiConnected`).
///
/// Sources, all real — nothing here is invented:
/// - Connectivity + transport type: `NWPathMonitor` (its `pathUpdateHandler`
///   also drives `NetworkChanged` events in SmartRemoteNative).
/// - SSID / BSSID: `CNCopyCurrentNetworkInfo` ("en0") first, then
///   `NEHotspotNetwork.fetchCurrent`. On iOS 13+ both return nil unless the
///   app has the "Access WiFi Information" capability
///   (`com.apple.developer.networking.wifi-info`) — see ios/README.md.
///   Without it the SSID is reported as null, never guessed.
/// - IPv4 address + subnet mask: `getifaddrs` on the Wi-Fi interface
///   (`en0`), via `getnameinfo`.
/// - Gateway: iOS exposes no public API for the default gateway, so it is
///   always null. A sysctl route-table dump could in principle recover it,
///   but that parsing was deliberately not attempted without a Mac/Xcode to
///   test it against — a wrong pointer walk there would crash the module.
///
/// NEEDS ON-DEVICE VERIFICATION: no Mac/Xcode was available when this was
/// written, so the SSID behaviour (with/without the wifi-info capability)
/// and the `NWPathMonitor` emissions have not been run on a real iPhone.
final class NetworkInfoProvider {

    /// How long `snapshot` waits for the (async) SSID lookup before
    /// resolving with a null SSID, so a hung lookup can never hang the
    /// JS promise.
    private static let ssidTimeoutSeconds: TimeInterval = 2.5

    private let monitor = NWPathMonitor()
    private let monitorQueue = DispatchQueue(label: "com.universalremote.network-monitor")
    private let pathLock = NSLock()
    private var cachedPath: NWPath?

    /// Called on every path update (connectivity/type change). The module
    /// uses it to emit `NetworkChanged`.
    var onPathChange: (() -> Void)?

    init() {
        monitor.pathUpdateHandler = { [weak self] path in
            guard let self = self else { return }
            self.pathLock.lock()
            self.cachedPath = path
            self.pathLock.unlock()
            self.onPathChange?()
        }
        monitor.start(queue: monitorQueue)
    }

    func stop() {
        monitor.cancel()
    }

    /// The most recent path. `pathUpdateHandler` fires immediately after
    /// `start`, so this is warm within milliseconds of module creation.
    /// `NWPathMonitor.currentPath` is used as a fallback where available.
    private var currentPath: NWPath? {
        pathLock.lock()
        defer { pathLock.unlock() }
        if let cached = cachedPath {
            return cached
        }
        if #available(iOS 14.0, *) {
            return monitor.currentPath
        }
        return nil
    }

    func isWifiConnected() -> Bool {
        guard let path = currentPath else { return false }
        return path.status == .satisfied && path.usesInterfaceType(.wifi)
    }

    /// Builds the full `NetworkInfo` dictionary (CONTRACTS.md §3).
    /// Values the OS will not disclose are `NSNull` (JS `null`), never
    /// invented. The completion is always called exactly once.
    func snapshot(completion: @escaping ([String: Any]) -> Void) {
        let path = currentPath
        let connected = path?.status == .satisfied
        let isWifi = path?.usesInterfaceType(.wifi) ?? false
        let isCellular = path?.usesInterfaceType(.cellular) ?? false
        let (ipAddress, subnetMask) = Self.wifiInterfaceAddresses()

        // Guard against double completion: the SSID lookup and the timeout
        // race, and whichever wins resolves the dictionary.
        let stateLock = NSLock()
        var didComplete = false
        let finish: (String?, String?) -> Void = { ssid, bssid in
            stateLock.lock()
            defer { stateLock.unlock() }
            guard !didComplete else { return }
            didComplete = true
            completion([
                "connected": connected,
                "isWifi": isWifi,
                "isCellular": isCellular,
                "ssid": ssid ?? NSNull(),
                "bssid": bssid ?? NSNull(),
                "ipAddress": ipAddress ?? NSNull(),
                "subnetMask": subnetMask ?? NSNull(),
                // No public iOS API exposes the default gateway (see header).
                "gateway": NSNull(),
            ])
        }

        fetchSSID { ssid, bssid in finish(ssid, bssid) }
        DispatchQueue.global().asyncAfter(deadline: .now() + Self.ssidTimeoutSeconds) {
            finish(nil, nil)
        }
    }

    // MARK: - SSID / BSSID

    private func fetchSSID(completion: @escaping (String?, String?) -> Void) {
        // 1. CaptiveNetwork. Deprecated in iOS 14 but still functional; on
        //    iOS 13+ it returns nil without the wifi-info capability or
        //    location permission (see header comment).
        if let info = CNCopyCurrentNetworkInfo("en0" as CFString) as? [String: Any],
           let ssid = info[kCNNetworkInfoKeySSID as String] as? String,
           !ssid.isEmpty {
            completion(ssid, info[kCNNetworkInfoKeyBSSID as String] as? String)
            return
        }
        // 2. NEHotspotNetwork. Also requires the wifi-info capability.
        NEHotspotNetwork.fetchCurrent { network in
            completion(network?.ssid, network?.bssid)
        }
    }

    // MARK: - IPv4 address / subnet mask via getifaddrs

    private static func wifiInterfaceAddresses() -> (ip: String?, netmask: String?) {
        var ifaddr: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddr) == 0, let first = ifaddr else {
            return (nil, nil)
        }
        defer { freeifaddrs(first) }

        var ip: String?
        var mask: String?
        var cursor: UnsafeMutablePointer<ifaddrs>? = first
        while let current = cursor {
            defer { cursor = current.pointee.ifa_next }
            guard String(cString: current.pointee.ifa_name) == "en0" else { continue }
            let flags = Int32(current.pointee.ifa_flags)
            guard (flags & Int32(IFF_UP)) != 0,
                  (flags & Int32(IFF_RUNNING)) != 0,
                  (flags & Int32(IFF_LOOPBACK)) == 0 else { continue }
            if ip == nil, let addr = current.pointee.ifa_addr {
                ip = ipv4String(from: addr)
            }
            if mask == nil, let netmask = current.pointee.ifa_netmask {
                mask = ipv4String(from: netmask)
            }
            if ip != nil, mask != nil { break }
        }
        return (ip, mask)
    }

    private static func ipv4String(from sockaddrPtr: UnsafeMutablePointer<sockaddr>) -> String? {
        guard sockaddrPtr.pointee.sa_family == sa_family_t(AF_INET) else { return nil }
        var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
        let result = getnameinfo(sockaddrPtr,
                                 socklen_t(MemoryLayout<sockaddr_in>.size),
                                 &host, socklen_t(host.count),
                                 nil, 0, NI_NUMERICHOST)
        guard result == 0 else { return nil }
        return String(cString: host)
    }
}
