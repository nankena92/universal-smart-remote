import Foundation

/// React Native bridge module `SmartRemoteNative` (CONTRACTS.md §3).
/// Discovery + network info only — it never sends remote keys.
///
/// Promise methods (exposed to React Native via SmartRemoteNative.m):
///   getNetworkInfo()   -> {connected, isWifi, isCellular, ssid, bssid,
///                          ipAddress, subnetMask, gateway}
///   isWifiConnected()  -> Bool
///   startDiscovery()   -> void (emits `TvDiscovered` as TVs answer)
///   stopDiscovery()    -> void
///
/// Events (names exact, per CONTRACTS.md §3):
///   `TvDiscovered`   {tv: DiscoveredTv}
///   `NetworkChanged` {connected, ssid, ipAddress}
///
/// `startDiscovery` resolves once browsing is confirmed running. If the
/// user denies Local Network access, the Bonjour browse fails fast and the
/// promise rejects with code `LOCAL_NETWORK_DENIED` and a message telling
/// them to enable it in Settings — never a faked empty result. If the user
/// takes longer than the 3-second grace period to answer the system prompt,
/// the promise still resolves and discovery keeps running in the
/// background; a denial after that surfaces on the next `startDiscovery`
/// call (a denied permission fails immediately, with no new prompt).
///
/// NEEDS ON-DEVICE VERIFICATION: no Mac/Xcode was available when this was
/// written, so nothing here has been compiled against the React Native
/// headers or run on a real iPhone. See ios/README.md.
@objc(SmartRemoteNative)
final class SmartRemoteNative: RCTEventEmitter {

    // MARK: - Module plumbing

    override static func requiresMainQueueSetup() -> Bool { false }

    override func supportedEvents() -> [String] {
        ["TvDiscovered", "NetworkChanged"]
    }

    override func startObserving() { hasListeners = true }
    override func stopObserving() { hasListeners = false }

    // MARK: - State

    private let networkProvider = NetworkInfoProvider()
    private let discovery = TvDiscovery()
    private var hasListeners = false
    private var lastNetworkStateKey: String?

    /// A `startDiscovery` promise still inside its grace period. All access
    /// happens on the main queue: module methods arrive on React Native's
    /// method queue while discovery callbacks arrive on the main queue, and
    /// these two must not race — so `startDiscovery` / `stopDiscovery`
    /// dispatch their pending-promise handling to the main queue.
    private var pendingStartResolve: RCTPromiseResolveBlock?
    private var pendingStartReject: RCTPromiseRejectBlock?
    private var startDiscoveryTimeout: DispatchWorkItem?

    override init() {
        super.init()
        discovery.onTvFound = { [weak self] tv in
            self?.emitTvDiscovered(tv)
        }
        discovery.onBrowserFailed = { [weak self] message in
            self?.handleDiscoveryFailure(message)
        }
        networkProvider.onPathChange = { [weak self] in
            self?.emitNetworkChanged()
        }
    }

    override func invalidate() {
        discovery.stop()
        networkProvider.stop()
        super.invalidate()
    }

    // MARK: - Promise methods (signatures must match SmartRemoteNative.m)

    @objc func getNetworkInfo(_ resolve: @escaping RCTPromiseResolveBlock,
                              rejecter reject: @escaping RCTPromiseRejectBlock) {
        networkProvider.snapshot { info in resolve(info) }
    }

    @objc func isWifiConnected(_ resolve: @escaping RCTPromiseResolveBlock,
                               rejecter reject: @escaping RCTPromiseRejectBlock) {
        resolve(networkProvider.isWifiConnected())
    }

    @objc func startDiscovery(_ resolve: @escaping RCTPromiseResolveBlock,
                              rejecter reject: @escaping RCTPromiseRejectBlock) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            // Idempotent, like the Android module: already running (or a
            // start already in flight) just resolves.
            if self.discovery.isDiscovering || self.pendingStartResolve != nil {
                resolve(nil)
                return
            }
            self.pendingStartResolve = resolve
            self.pendingStartReject = reject
            self.discovery.start()
            // Grace period: resolve once browsing is confirmed running
            // (see the header comment for the denial/timeout behaviour).
            let timeout = DispatchWorkItem { [weak self] in
                self?.settlePendingStart(resolve: true, message: nil)
            }
            self.startDiscoveryTimeout = timeout
            DispatchQueue.main.asyncAfter(deadline: .now() + 3.0, execute: timeout)
        }
    }

    @objc func stopDiscovery(_ resolve: @escaping RCTPromiseResolveBlock,
                             rejecter reject: @escaping RCTPromiseRejectBlock) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            // A stop must never leave a startDiscovery promise dangling.
            self.settlePendingStart(resolve: true, message: nil)
            self.discovery.stop()
            resolve(nil)
        }
    }

    // MARK: - Events

    /// First successful result proves discovery is running: settle a
    /// pending `startDiscovery` promise early so the UI stops spinning.
    /// The TypeScript wrapper (`mobile/src/services/native.ts`) also
    /// accepts a bare `DiscoveredTv` payload; this emits `{tv}` per §3.
    private func emitTvDiscovered(_ tv: [String: Any]) {
        settlePendingStart(resolve: true, message: nil)
        guard hasListeners else { return }
        sendEvent(withName: "TvDiscovered", body: ["tv": tv])
    }

    private func emitNetworkChanged() {
        networkProvider.snapshot { [weak self] info in
            DispatchQueue.main.async {
                guard let self = self, self.hasListeners else { return }
                let connected = info["connected"] as? Bool ?? false
                let ssid = info["ssid"] as? String
                let ip = info["ipAddress"] as? String
                // Dedupe, like the Android module: same state, no re-emit.
                let key = "\(connected)|\(ssid ?? "")|\(ip ?? "")"
                guard key != self.lastNetworkStateKey else { return }
                self.lastNetworkStateKey = key
                self.sendEvent(withName: "NetworkChanged", body: [
                    "connected": connected,
                    "ssid": ssid ?? NSNull(),
                    "ipAddress": ip ?? NSNull(),
                ])
            }
        }
    }

    // MARK: - Discovery failure

    private func handleDiscoveryFailure(_ message: String) {
        // Only a pending startDiscovery can still be rejected. A failure
        // that arrives mid-session has no promise to reject; the next
        // startDiscovery call will surface the error when it fails again
        // (denied permission fails immediately, without a new prompt).
        settlePendingStart(resolve: false, message: message)
    }

    /// Settles a pending `startDiscovery` promise, if any. Main queue only.
    private func settlePendingStart(resolve: Bool, message: String?) {
        startDiscoveryTimeout?.cancel()
        startDiscoveryTimeout = nil
        let resolveBlock = pendingStartResolve
        let rejectBlock = pendingStartReject
        pendingStartResolve = nil
        pendingStartReject = nil
        if resolve {
            resolveBlock?(nil)
        } else {
            rejectBlock?("LOCAL_NETWORK_DENIED",
                         message ?? "Local network access was denied.",
                         nil)
        }
    }
}
