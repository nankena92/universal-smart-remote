package com.universalremote;

import android.Manifest;
import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.net.DhcpInfo;
import android.os.Build;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.core.content.ContextCompat;

import com.facebook.react.bridge.Arguments;
import com.facebook.react.bridge.Promise;
import com.facebook.react.bridge.ReactApplicationContext;
import com.facebook.react.bridge.ReactContextBaseJavaModule;
import com.facebook.react.bridge.ReactMethod;
import com.facebook.react.bridge.WritableMap;
import com.facebook.react.modules.core.DeviceEventManagerModule;
import com.facebook.react.modules.core.PermissionAwareActivity;
import com.facebook.react.modules.core.PermissionListener;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.DatagramPacket;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.MulticastSocket;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Native module "SmartRemoteNative" — discovery + network only.
 * It does NOT send remote keys (see CONTRACTS.md §3); keys go to the
 * FastAPI backend (backend mode) or are sent from JS (direct mode).
 *
 * Methods (CONTRACTS.md §3): getNetworkInfo, isWifiConnected,
 * startDiscovery, stopDiscovery.
 *
 * Event names (exact, per CONTRACTS.md §3):
 *   - "TvDiscovered"   {tv: {name, brand, model, ip, port, mac, source: 'ssdp'}}
 *   - "NetworkChanged" {connected, ssid, ipAddress}
 *
 * Failure paths return real errors, never faked data:
 *   - getNetworkInfo: PERMISSION_DENIED when location permission (needed
 *     for the SSID on Android 10+) is denied.
 *   - startDiscovery: WIFI_DISABLED when Wi-Fi is off, MULTICAST_ERROR
 *     when the Wi-Fi multicast lock cannot be acquired, DISCOVERY_ERROR
 *     when the SSDP socket cannot be opened.
 *   - SSDP carries no MAC address, so mac is null — never invented.
 *
 * NEEDS ON-DEVICE VERIFICATION: no Android device/SDK was available when
 * this was written, so the SSDP flow, SSID behaviour on Android 10+ and
 * the NetworkCallback emissions have not been run against a real device.
 */
public class SmartRemoteNativeModule extends ReactContextBaseJavaModule {

    private static final String TAG = "SmartRemoteNative";
    private static final String MODULE_NAME = "SmartRemoteNative";

    /** SSDP multicast group/port (UPnP Device Architecture). */
    private static final String SSDP_ADDRESS = "239.255.255.250";
    private static final int SSDP_PORT = 1900;
    /** How long receive() blocks before we re-send M-SEARCH. */
    private static final int SSDP_SOCKET_TIMEOUT_MS = 3000;
    /** Max time spent fetching a device description XML for a friendly name. */
    private static final int DESCRIPTION_TIMEOUT_MS = 2000;
    private static final int DESCRIPTION_MAX_BYTES = 64 * 1024;

    private static final int REQUEST_LOCATION_FOR_NETWORK_INFO = 1001;

    /** ST values probed on every M-SEARCH round (generic + targeted). */
    private static final String[] SEARCH_TARGETS = {
            "ssdp:all",
            "upnp:rootdevice",
            "urn:samsung.com:device:RemoteControlReceiver:1",
            "urn:dial-multiscreen-org:service:dial:1"
    };

    private final ReactApplicationContext reactContext;

    // ---- discovery state ----
    private volatile boolean discovering = false;
    private Thread discoveryThread;
    private MulticastSocket discoverySocket;
    private WifiManager.MulticastLock multicastLock;
    /** Dedupe key: ip + "|" + USN (or ST when USN is absent). */
    private final Set<String> seenDevices = ConcurrentHashMap.newKeySet();

    // ---- network-change state ----
    private ConnectivityManager.NetworkCallback networkCallback;
    private BroadcastReceiver connectivityReceiver;
    private boolean networkMonitoringRegistered = false;
    /** Last emitted NetworkChanged tuple, to avoid duplicate events. */
    private String lastNetworkStateKey = null;

    // ---- pending permission flow ----
    private Promise pendingNetworkInfoPromise;

    private final PermissionListener permissionListener = new PermissionListener() {
        @Override
        public boolean onRequestPermissionsResult(int requestCode,
                                                  String[] permissions,
                                                  int[] grantResults) {
            if (requestCode != REQUEST_LOCATION_FOR_NETWORK_INFO) {
                return false;
            }
            Promise promise = pendingNetworkInfoPromise;
            pendingNetworkInfoPromise = null;
            if (promise == null) {
                return true;
            }
            if (grantResults.length > 0
                    && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                resolveNetworkInfo(promise);
            } else {
                // Real rejection, not a faked SSID: without location permission
                // Android 10+ will not give us the SSID at all.
                promise.reject("PERMISSION_DENIED",
                        "Location permission is required on Android 10+ to read the "
                                + "Wi-Fi SSID. Grant location permission and try again.");
            }
            return true;
        }
    };

    public SmartRemoteNativeModule(ReactApplicationContext reactContext) {
        super(reactContext);
        this.reactContext = reactContext;
    }

    @NonNull
    @Override
    public String getName() {
        return MODULE_NAME;
    }

    // ------------------------------------------------------------------
    // Lifecycle: network monitoring
    // ------------------------------------------------------------------

    @Override
    public void initialize() {
        super.initialize();
        registerNetworkMonitoring();
    }

    @Override
    public void onCatalystInstanceDestroy() {
        stopDiscoveryInternal();
        unregisterNetworkMonitoring();
        super.onCatalystInstanceDestroy();
    }

    /**
     * Primary mechanism: ConnectivityManager.NetworkCallback (API 21+).
     * Fallback: a context-registered BroadcastReceiver for
     * CONNECTIVITY_ACTION, which is still delivered to context-registered
     * receivers on API 24+ (only manifest registration was restricted).
     * Emissions are deduped on (connected, ssid, ip), so receiving the
     * same change through both paths only emits once.
     */
    private void registerNetworkMonitoring() {
        if (networkMonitoringRegistered) {
            return;
        }
        ConnectivityManager cm = getConnectivityManager();
        if (cm != null) {
            networkCallback = new ConnectivityManager.NetworkCallback() {
                @Override
                public void onAvailable(@NonNull Network network) {
                    emitNetworkChanged();
                }

                @Override
                public void onLost(@NonNull Network network) {
                    emitNetworkChanged();
                }

                @Override
                public void onCapabilitiesChanged(@NonNull Network network,
                                                  @NonNull NetworkCapabilities caps) {
                    emitNetworkChanged();
                }
            };
            NetworkRequest request = new NetworkRequest.Builder()
                    .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                    .build();
            try {
                cm.registerNetworkCallback(request, networkCallback);
            } catch (Exception e) {
                Log.w(TAG, "registerNetworkCallback failed, relying on receiver", e);
                networkCallback = null;
            }
        }

        connectivityReceiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                if (ConnectivityManager.CONNECTIVITY_ACTION.equals(intent.getAction())) {
                    emitNetworkChanged();
                }
            }
        };
        try {
            reactContext.registerReceiver(
                    connectivityReceiver,
                    new IntentFilter(ConnectivityManager.CONNECTIVITY_ACTION));
            networkMonitoringRegistered = true;
        } catch (Exception e) {
            Log.w(TAG, "Could not register connectivity receiver", e);
        }
    }

    private void unregisterNetworkMonitoring() {
        if (!networkMonitoringRegistered) {
            return;
        }
        networkMonitoringRegistered = false;
        ConnectivityManager cm = getConnectivityManager();
        if (cm != null && networkCallback != null) {
            try {
                cm.unregisterNetworkCallback(networkCallback);
            } catch (Exception e) {
                Log.w(TAG, "unregisterNetworkCallback failed", e);
            }
            networkCallback = null;
        }
        if (connectivityReceiver != null) {
            try {
                reactContext.unregisterReceiver(connectivityReceiver);
            } catch (Exception e) {
                Log.w(TAG, "unregisterReceiver failed", e);
            }
            connectivityReceiver = null;
        }
    }

    private void emitNetworkChanged() {
        if (!reactContext.hasActiveCatalystInstance()) {
            return;
        }
        WritableMap info = buildNetworkInfoMap();
        boolean connected = info.getBoolean("connected");
        String ssid = info.hasKey("ssid") ? info.getString("ssid") : null;
        String ip = info.hasKey("ipAddress") ? info.getString("ipAddress") : null;

        String stateKey = connected + "|" + ssid + "|" + ip;
        if (stateKey.equals(lastNetworkStateKey)) {
            return; // already emitted this exact state
        }
        lastNetworkStateKey = stateKey;

        WritableMap event = Arguments.createMap();
        event.putBoolean("connected", connected);
        event.putString("ssid", ssid);
        event.putString("ipAddress", ip);
        sendEvent("NetworkChanged", event);
    }

    // ------------------------------------------------------------------
    // Network info
    // ------------------------------------------------------------------

    /**
     * Returns {connected, isWifi, isCellular, ssid, bssid, ipAddress,
     * subnetMask, gateway} per CONTRACTS.md §3.
     *
     * Android 10+ (API 29) requires ACCESS_FINE_LOCATION to read the SSID
     * (coarse location is not enough): if the permission is missing we
     * request it (via the current activity); if the user denies it the
     * promise is rejected with code "PERMISSION_DENIED". On API < 29 the
     * SSID is readable without location permission, so no request is made.
     * If permission is granted but the SSID is still unavailable (not on
     * Wi-Fi, or the OS returns "<unknown ssid>"), ssid is reported as
     * null honestly — never faked.
     */
    @ReactMethod
    public void getNetworkInfo(Promise promise) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
                && !hasFineLocationPermission()) {
            if (pendingNetworkInfoPromise != null) {
                promise.reject("PERMISSION_PENDING",
                        "A location permission request for network info is already in progress.");
                return;
            }
            Activity activity = getCurrentActivity();
            if (activity instanceof PermissionAwareActivity) {
                pendingNetworkInfoPromise = promise;
                ((PermissionAwareActivity) activity).requestPermissions(
                        new String[]{Manifest.permission.ACCESS_FINE_LOCATION},
                        REQUEST_LOCATION_FOR_NETWORK_INFO,
                        permissionListener);
                return;
            }
            promise.reject("PERMISSION_DENIED",
                    "Location permission is required on Android 10+ to read the "
                            + "Wi-Fi SSID, and no activity is available to request it.");
            return;
        }
        resolveNetworkInfo(promise);
    }

    private void resolveNetworkInfo(Promise promise) {
        try {
            promise.resolve(buildNetworkInfoMap());
        } catch (Exception e) {
            Log.e(TAG, "getNetworkInfo failed", e);
            promise.reject("NETWORK_INFO_ERROR",
                    "Could not read network info: " + e.getMessage(), e);
        }
    }

    private WritableMap buildNetworkInfoMap() {
        WritableMap map = Arguments.createMap();

        ConnectivityManager cm = getConnectivityManager();
        NetworkCapabilities caps = null;
        if (cm != null) {
            Network active = cm.getActiveNetwork();
            if (active != null) {
                caps = cm.getNetworkCapabilities(active);
            }
        }
        boolean connected = caps != null
                && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
        boolean isWifi = caps != null
                && caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI);
        boolean isCellular = caps != null
                && caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR);

        map.putBoolean("connected", connected);
        map.putBoolean("isWifi", isWifi);
        map.putBoolean("isCellular", isCellular);

        String ssid = null;
        String bssid = null;
        String ipAddress = null;
        String subnetMask = null;
        String gateway = null;

        WifiManager wifiManager = getWifiManager();
        if (wifiManager != null) {
            // getConnectionInfo() is deprecated in API 31 but still returns
            // the current WifiInfo on Android 13/14; there is no replacement
            // that exposes the SSID to a normal app.
            WifiInfo info = wifiManager.getConnectionInfo();
            if (info != null) {
                ssid = sanitizeSsid(info.getSSID());
                bssid = sanitizeBssid(info.getBSSID());
            }
            DhcpInfo dhcp = wifiManager.getDhcpInfo();
            if (dhcp != null) {
                ipAddress = intToIp(dhcp.ipAddress);
                subnetMask = intToIp(dhcp.netmask);
                gateway = intToIp(dhcp.gateway);
            }
        }

        // nulls are honest: e.g. no Wi-Fi connection, or the OS withheld
        // the SSID. The TS side (mobile/src/services/native.ts) treats
        // null as "unknown".
        map.putString("ssid", ssid);
        map.putString("bssid", bssid);
        map.putString("ipAddress", ipAddress);
        map.putString("subnetMask", subnetMask);
        map.putString("gateway", gateway);
        return map;
    }

    /** True when the active network is a Wi-Fi transport. */
    @ReactMethod
    public void isWifiConnected(Promise promise) {
        try {
            ConnectivityManager cm = getConnectivityManager();
            boolean wifi = false;
            if (cm != null) {
                Network active = cm.getActiveNetwork();
                if (active != null) {
                    NetworkCapabilities caps = cm.getNetworkCapabilities(active);
                    wifi = caps != null
                            && caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI);
                }
            }
            promise.resolve(wifi);
        } catch (Exception e) {
            Log.e(TAG, "isWifiConnected failed", e);
            promise.reject("NETWORK_INFO_ERROR",
                    "Could not determine Wi-Fi state: " + e.getMessage(), e);
        }
    }

    // ------------------------------------------------------------------
    // SSDP discovery
    // ------------------------------------------------------------------

    /**
     * Starts SSDP M-SEARCH discovery and resolves once the search loop is
     * running. TVs are delivered as they answer, via 'TvDiscovered'
     * events — not via the promise result. Idempotent: calling it while
     * already discovering just resolves.
     *
     * The socket is opened synchronously here (on the native-modules
     * thread) so a real failure can reject the promise instead of failing
     * silently on the background thread:
     *   - WIFI_DISABLED: Wi-Fi is off, so multicast cannot reach the LAN.
     *   - MULTICAST_ERROR: the Wi-Fi multicast lock could not be acquired.
     *   - DISCOVERY_ERROR: the SSDP socket (UDP 1900) could not be opened.
     */
    @ReactMethod
    @SuppressWarnings("deprecation") // MulticastSocket.joinGroup(InetAddress)
    public void startDiscovery(Promise promise) {
        if (discovering) {
            promise.resolve(null);
            return;
        }

        WifiManager wifiManager = getWifiManager();
        if (wifiManager == null || !wifiManager.isWifiEnabled()) {
            promise.reject("WIFI_DISABLED",
                    "Wi-Fi is off. Turn on Wi-Fi and connect to the same network "
                            + "as your TV, then try again.");
            return;
        }

        // Multicast packets are dropped by default on Android; the lock
        // must be held for the whole discovery session and released in
        // stopDiscoveryInternal().
        try {
            multicastLock = wifiManager.createMulticastLock("SmartRemoteDiscoveryLock");
            multicastLock.setReferenceCounted(true);
            multicastLock.acquire();
        } catch (Exception e) {
            Log.e(TAG, "Could not acquire multicast lock", e);
            multicastLock = null;
            promise.reject("MULTICAST_ERROR",
                    "Could not acquire the Wi-Fi multicast lock, so SSDP discovery "
                            + "cannot receive replies: " + e.getMessage(), e);
            return;
        }

        MulticastSocket socket = null;
        try {
            // Bind explicitly so setReuseAddress(true) takes effect before
            // the bind; otherwise a second app instance can fail to bind.
            socket = new MulticastSocket(null);
            socket.setReuseAddress(true);
            socket.bind(new InetSocketAddress(SSDP_PORT));
            socket.setSoTimeout(SSDP_SOCKET_TIMEOUT_MS);
            InetAddress group = InetAddress.getByName(SSDP_ADDRESS);
            socket.joinGroup(group);
        } catch (IOException e) {
            Log.e(TAG, "SSDP socket setup failed", e);
            if (socket != null) {
                socket.close();
            }
            releaseMulticastLock();
            promise.reject("DISCOVERY_ERROR",
                    "Could not open the SSDP discovery socket (UDP port 1900): "
                            + e.getMessage(), e);
            return;
        }

        discovering = true;
        seenDevices.clear();
        discoverySocket = socket;
        final MulticastSocket boundSocket = socket;
        discoveryThread = new Thread(() -> runDiscoveryLoop(boundSocket),
                "SmartRemote-Ssdp");
        discoveryThread.setDaemon(true);
        discoveryThread.start();
        promise.resolve(null);
    }

    /** Stops discovery cleanly: closes the socket (unblocks receive()),
     * joins the thread briefly, and releases the multicast lock. */
    @ReactMethod
    public void stopDiscovery(Promise promise) {
        stopDiscoveryInternal();
        promise.resolve(null);
    }

    private void stopDiscoveryInternal() {
        discovering = false;
        if (discoverySocket != null) {
            try {
                discoverySocket.close();
            } catch (Exception e) {
                Log.w(TAG, "Error closing discovery socket", e);
            }
            discoverySocket = null;
        }
        if (discoveryThread != null) {
            try {
                discoveryThread.join(2000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            discoveryThread = null;
        }
        releaseMulticastLock();
    }

    private void releaseMulticastLock() {
        if (multicastLock != null && multicastLock.isHeld()) {
            try {
                multicastLock.release();
            } catch (Exception e) {
                Log.w(TAG, "Error releasing multicast lock", e);
            }
        }
        multicastLock = null;
    }

    /**
     * Receive loop on the discovery thread. Re-sends M-SEARCH after each
     * quiet window so TVs that came online late (or missed the first
     * packet) still get discovered. The socket is owned by this loop once
     * started; stopDiscoveryInternal() closes it to unblock receive().
     */
    @SuppressWarnings("deprecation") // MulticastSocket.leaveGroup(InetAddress)
    private void runDiscoveryLoop(MulticastSocket socket) {
        try {
            InetAddress group = InetAddress.getByName(SSDP_ADDRESS);
            sendSearchRequests(socket, group);

            byte[] buffer = new byte[8192];
            while (discovering) {
                DatagramPacket packet = new DatagramPacket(buffer, buffer.length);
                try {
                    socket.receive(packet);
                } catch (SocketTimeoutException e) {
                    // No answer in this window: re-broadcast M-SEARCH.
                    if (discovering) {
                        sendSearchRequests(socket, group);
                    }
                    continue;
                } catch (IOException e) {
                    if (discovering) {
                        Log.w(TAG, "SSDP receive error", e);
                    }
                    break; // socket closed by stopDiscovery()
                }
                handleSsdpResponse(packet);
            }
        } catch (IOException e) {
            Log.e(TAG, "SSDP discovery failed", e);
        } finally {
            try {
                socket.leaveGroup(InetAddress.getByName(SSDP_ADDRESS));
            } catch (Exception ignored) {
                // Best effort; the socket is being torn down anyway.
            }
            socket.close();
            if (discoverySocket == socket) {
                discoverySocket = null;
            }
            discovering = false;
        }
    }

    private void sendSearchRequests(MulticastSocket socket, InetAddress group) {
        for (String st : SEARCH_TARGETS) {
            String request = "M-SEARCH * HTTP/1.1\r\n"
                    + "HOST: " + SSDP_ADDRESS + ":" + SSDP_PORT + "\r\n"
                    + "MAN: \"ns=01\"\r\n"
                    + "MX: 3\r\n"
                    + "ST: " + st + "\r\n"
                    + "USER-AGENT: UniversalSmartRemote/1.0 UPnP/1.0\r\n"
                    + "\r\n";
            byte[] data = request.getBytes(StandardCharsets.UTF_8);
            try {
                socket.send(new DatagramPacket(data, data.length, group, SSDP_PORT));
            } catch (IOException e) {
                Log.w(TAG, "Failed to send M-SEARCH (ST=" + st + ")", e);
            }
        }
    }

    private void handleSsdpResponse(DatagramPacket packet) {
        String text = new String(packet.getData(), 0, packet.getLength(),
                StandardCharsets.UTF_8);
        Map<String, String> headers = parseSsdpHeaders(text);
        String location = headers.get("location");
        String usn = headers.get("usn");
        String st = headers.get("st");
        String server = headers.get("server");

        // LOCATION is the device description URL; fall back to the
        // sender's address when a device answers without one.
        String ip = packet.getAddress().getHostAddress();
        int port = 80;
        if (location != null) {
            try {
                URL url = new URL(location);
                ip = url.getHost();
                port = url.getPort() != -1 ? url.getPort()
                        : ("https".equalsIgnoreCase(url.getProtocol()) ? 443 : 80);
            } catch (Exception e) {
                Log.w(TAG, "Could not parse LOCATION header: " + location, e);
            }
        }
        if (ip == null) {
            return;
        }

        String dedupeKey = ip + "|" + (usn != null ? usn : (st != null ? st : ""));
        if (!seenDevices.add(dedupeKey)) {
            return; // same device answering a repeated M-SEARCH round
        }

        String brand = resolveBrand(server, usn, st);

        // Best effort: fetch the description XML for the friendly name
        // and model. Time-boxed; any failure leaves name/model blank
        // rather than blocking discovery.
        String name = null;
        String model = "";
        if (location != null) {
            String[] desc = fetchDeviceDescription(location);
            if (desc != null) {
                name = desc[0];
                if (desc[1] != null) {
                    model = desc[1];
                }
            }
        }
        if (name == null || name.isEmpty()) {
            name = friendlyBrandName(brand);
        }

        WritableMap tv = Arguments.createMap();
        tv.putString("name", name);
        tv.putString("brand", brand);
        tv.putString("model", model);
        tv.putString("ip", ip);
        tv.putInt("port", port);
        // SSDP carries no MAC address; null is honest. The backend/JS
        // side may fill it in later (e.g. from ARP) if it ever needs it.
        tv.putString("mac", null);
        tv.putString("source", "ssdp");

        // CONTRACTS.md §3 event shape: {tv: DiscoveredTv}.
        WritableMap event = Arguments.createMap();
        event.putMap("tv", tv);
        sendEvent("TvDiscovered", event);
    }

    /** Parses SSDP response headers into a lower-cased-key map. */
    private static Map<String, String> parseSsdpHeaders(String text) {
        Map<String, String> headers = new HashMap<>();
        String[] lines = text.split("\r\n");
        for (int i = 1; i < lines.length; i++) { // line 0 is the status line
            int colon = lines[i].indexOf(':');
            if (colon > 0) {
                String key = lines[i].substring(0, colon).trim()
                        .toLowerCase(Locale.US);
                String value = lines[i].substring(colon + 1).trim();
                headers.put(key, value);
            }
        }
        return headers;
    }

    /**
     * Best-effort brand detection from SERVER / USN / ST headers.
     * Returns "unknown" when nothing matches (CONTRACTS.md §2).
     */
    private static String resolveBrand(String server, String usn, String st) {
        String hay = ((server != null ? server : "") + " "
                + (usn != null ? usn : "") + " "
                + (st != null ? st : "")).toLowerCase(Locale.US);
        if (hay.contains("samsung")) {
            return "samsung";
        }
        if (hay.contains("roku")) {
            return "roku";
        }
        if (hay.contains("lg") || hay.contains("webos")) {
            return "lg";
        }
        if (hay.contains("sony") || hay.contains("bravia")) {
            return "sony";
        }
        if (hay.contains("tcl")) {
            return "tcl";
        }
        if (hay.contains("android") || hay.contains("google")
                || hay.contains("chromecast")) {
            return "androidtv";
        }
        return "unknown";
    }

    private static String friendlyBrandName(String brand) {
        switch (brand) {
            case "samsung":
                return "Samsung TV";
            case "roku":
                return "Roku TV";
            case "lg":
                return "LG TV";
            case "sony":
                return "Sony TV";
            case "tcl":
                return "TCL TV";
            case "androidtv":
                return "Android TV";
            default:
                return "Unknown TV";
        }
    }

    /**
     * Fetches the UPnP device description XML at the LOCATION URL and
     * extracts friendlyName / modelName. Returns {friendlyName, modelName}
     * or null on any failure. Runs on the discovery thread, never the UI
     * thread, and is strictly time-boxed.
     */
    private static String[] fetchDeviceDescription(String locationUrl) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(locationUrl);
            conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(DESCRIPTION_TIMEOUT_MS);
            conn.setReadTimeout(DESCRIPTION_TIMEOUT_MS);
            conn.setRequestMethod("GET");
            conn.setRequestProperty("Accept", "text/xml");
            if (conn.getResponseCode() != HttpURLConnection.HTTP_OK) {
                return null;
            }
            InputStream in = conn.getInputStream();
            BufferedReader reader = new BufferedReader(
                    new InputStreamReader(in, StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            char[] buf = new char[4096];
            int read;
            int total = 0;
            while ((read = reader.read(buf)) != -1 && total < DESCRIPTION_MAX_BYTES) {
                sb.append(buf, 0, read);
                total += read;
            }
            String xml = sb.toString();
            return new String[]{
                    extractXmlTag(xml, "friendlyName"),
                    extractXmlTag(xml, "modelName")
            };
        } catch (Exception e) {
            Log.d(TAG, "Description fetch failed for " + locationUrl + ": " + e.getMessage());
            return null;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private static String extractXmlTag(String xml, String tag) {
        Matcher m = Pattern.compile("<" + tag + ">(.*?)</" + tag + ">",
                Pattern.DOTALL).matcher(xml);
        return m.find() ? m.group(1).trim() : null;
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    private void sendEvent(String eventName, WritableMap params) {
        if (!reactContext.hasActiveCatalystInstance()) {
            return;
        }
        reactContext
                .getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter.class)
                .emit(eventName, params);
    }

    private ConnectivityManager getConnectivityManager() {
        return (ConnectivityManager) reactContext.getSystemService(
                Context.CONNECTIVITY_SERVICE);
    }

    private WifiManager getWifiManager() {
        return (WifiManager) reactContext.getApplicationContext()
                .getSystemService(Context.WIFI_SERVICE);
    }

    /**
     * Android 10+ requires ACCESS_FINE_LOCATION to read the SSID;
     * ACCESS_COARSE_LOCATION alone does not unlock it.
     */
    private boolean hasFineLocationPermission() {
        return ContextCompat.checkSelfPermission(reactContext,
                Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED;
    }

    /**
     * WifiInfo.getSSID() returns the SSID in double quotes, e.g.
     * "\"HomeWifi\"", or "<unknown ssid>" when the OS will not disclose
     * it (no location permission, or not associated). Both cases map to
     * null here — never a fabricated value.
     */
    private static String sanitizeSsid(String raw) {
        if (raw == null || raw.isEmpty() || "<unknown ssid>".equals(raw)) {
            return null;
        }
        if (raw.length() >= 2 && raw.startsWith("\"") && raw.endsWith("\"")) {
            return raw.substring(1, raw.length() - 1);
        }
        return raw;
    }

    /**
     * Android returns the placeholder "02:00:00:00:00:00" when the real
     * BSSID is withheld; treat it as unknown.
     */
    private static String sanitizeBssid(String raw) {
        if (raw == null || raw.isEmpty() || "02:00:00:00:00:00".equals(raw)) {
            return null;
        }
        return raw;
    }

    /** DhcpInfo stores IPv4 addresses as little-endian ints; 0 = unset. */
    private static String intToIp(int value) {
        if (value == 0) {
            return null;
        }
        return (value & 0xff) + "."
                + ((value >> 8) & 0xff) + "."
                + ((value >> 16) & 0xff) + "."
                + ((value >> 24) & 0xff);
    }
}
