# iPhone-only install — free cloud build, no Mac, no laptop, no $99

This guide is for the owner of this app (iPhone only, no Mac, no laptop
to use, no paid Apple Developer account). It gets **your own code** onto
your iPhone so the remote works with no Python backend and no laptop
running.

## The short version

1. GitHub builds the app on a Mac in the cloud (free) and gives you an
   unsigned `.ipa` file.
2. You install that `.ipa` on your iPhone with SideStore (or AltStore),
   which signs it on the phone with a **free Apple ID**.
3. The app then talks **directly** from the phone to the TV over your
   home Wi-Fi — Samsung, LG and Roku in direct mode. No backend.

## What will NOT work, honestly

- **Disney+ launch on Samsung** is not supported in this app, in direct
  mode or backend mode. The app's own table lists no Samsung app id for
  Disney+ (the contract says `None`), so the button will honestly say it
  is not supported. Netflix, Prime Video and YouTube **do** have Samsung
  app ids and are expected to work. Power, D-pad, volume, channel,
  back/home/menu and playback keys all have Samsung key codes.
- **Sony, Android TV, Google TV, TCL and Fire TV** cannot be driven in
  direct mode — they still need the Python backend. This iPhone-only
  build is for Samsung (and LG / Roku) only.
- A free Apple ID signature lasts **7 days** and allows **3 sideloaded
  apps** per iPhone. Every week you open SideStore and tap Refresh.
  The app stops opening after 7 days if you do not refresh it.
- **The Samsung connection itself is unproven.** The phone app uses
  `wss://<TV>:8002` (the TV's self-signed certificate). A normal phone
  app cannot ignore a bad certificate the way the Python backend can,
  so the app now also tries plain `ws://<TV>:8001` if the secure channel
  fails. Whether the TV accepts that plain channel can only be settled
  by trying it on the real TV. If both fail, the app will show the real
  error — it will not pretend the TV is connected.
- **Discovery on iPhone is limited.** Apple's Multicast Networking
  entitlement (needed for SSDP discovery) is only granted on request
  to paid developer accounts, so this free build almost certainly
  discovers TVs by Bonjour only, and may find nothing at all. That is
  why the guide below uses **manual connect by IP**: the Samsung TV is
  at `192.168.1.178` (check it has not changed — see step 5).
- The Swift native module, the Xcode project generation, and the whole
  React Native 0.73 build have **never been compiled** until this
  workflow runs. The first cloud run may fail on a toolchain detail
  (for example if GitHub has removed Xcode 15.4 from the macos-14
  runner). That is a build failure to fix, not a sign the idea is
  impossible — but it is not proven until a green run produces an `.ipa`.

## Step 1 — Build the .ipa in the cloud (free)

No computer is needed for this step. It is done from the GitHub website.

1. On the iPhone, open Safari and go to
   `https://github.com/nankena92/universal-smart-remote`
2. Tap **Actions** at the top of the repo.
3. Tap the workflow **"Build iOS unsigned IPA"**.
4. Tap **Run workflow** (branch `main`), then **Run workflow** again.
5. Wait. It takes roughly 10–20 minutes. Refresh the page; the run
   turns green when it finishes.
6. Scroll to the bottom of the run, under **Artifacts**, and download
   **`universal-smart-remote-unsigned-ipa`**. Unzip it on the phone —
   inside is `UniversalSmartRemote-unsigned.ipa`.

If the run goes red, open the failed step and read its last lines.
The most likely failures are: Xcode 15.4 no longer on the runner
(the workflow fails loudly on purpose — do not just switch to a newer
Xcode, React Native 0.73 is not known to build with it), or the
generated Xcode project missing a file (compare with
`mobile/ios/README.md`).

The workflow file is `.github/workflows/build-ios-unsigned-ipa.yml`.
It must be in the GitHub repo before this step works — uploading it
is a separate step (the repo is updated through the GitHub website;
the direct GitHub connection cannot push to it).

## Step 2 — Get SideStore onto the iPhone

This is the hardest part, and it depends on the iPhone's iOS version.
Check it first: **Settings → General → About → iOS Version**.

- **iOS 27 or later:** SideInstaller works fully on-device, no
  computer at any point. On the iPhone, open Safari and go to
  `https://sideinstaller.net` — **only that address**, never a copy
  from another site — and follow its steps to install SideStore.
  SideInstaller signs with your Apple ID on the device only.
- **iOS 26.4–26.7:** SideInstaller works with a remote pairing file,
  made once on a computer. There is no fully on-device path on these
  versions.
- **iOS 17.4–26.3:** SideStore's own setup needs a computer **once**,
  to install it (AltServer / iloader) and create the pairing file.
  After that one setup, installs and refreshes happen on the phone
  alone, over Wi-Fi, through LocalDevVPN (from the App Store).
- **AltStore Classic 2.3+** is an alternative: its Remote AltServer
  can install and refresh from the phone, but its first setup also
  includes a pairing step with a computer.

There is no known way to install SideStore/AltStore on a US iPhone
with zero computer involvement on iOS below 27 — AltStore PAL (the
App-Store-style install with no computer) is EU/Japan/Brazil only,
and it does not install arbitrary `.ipa` files anyway.

**Apple ID safety — read this before typing anything:**
Use a **spare Apple ID made just for signing**, not the Apple ID that
holds your photos, mail and purchases. Never give your Apple ID or
password to me, to any website, or to any tool other than SideStore /
AltStore / SideInstaller itself, on your own phone. Only download
SideStore, SideInstaller and LocalDevVPN from their official sites /
the App Store. A copy from any other site is not safe to sign in to.

## Step 3 — Install the app on the iPhone

1. In SideStore, tap **+** (My Apps), pick
   `UniversalSmartRemote-unsigned.ipa` from Files, and sign in with
   the spare Apple ID when it asks.
2. When it asks, trust the developer profile:
   **Settings → General → VPN & Device Management → [your Apple ID]
   → Trust**.
3. The app appears on the Home Screen as **Universal Smart Remote**.
4. **Every 7 days**, open SideStore and tap Refresh (with LocalDevVPN
   connected) or the app will stop opening.

## Step 4 — Use it (no laptop, no backend)

1. Make sure the TV is **on**, and the iPhone and TV are on the
   **same Wi-Fi**.
2. Open the app. It starts in **Direct mode** by default (Settings →
   Control mode → Direct). Do not switch it to Backend mode — there
   is no backend in this build.
3. On first launch, allow the **Local Network** prompt. Without it
   the phone cannot see the TV at all.
4. Go to Discover. If the Samsung TV does not appear (see the Bonjour
   limit above), use **Connect by IP** instead:
   - IP: `192.168.1.178` (the Samsung 85" Neo QLED 90A found on
     2026-11-24 — if the TV was restarted or the router changed, this
     number may have changed; find the TV's current IP in the TV's
     Settings → Network, or in the router's device list)
   - Brand: **Samsung**
   - Name: Living Room TV
5. Look at the TV — it shows an **Allow** prompt for the new device.
   Accept it on the TV. The app saves the pairing token, so next time
   it should connect without asking again.
6. Use the remote: Power, D-pad, volume, channel, back/home/menu,
   playback, Netflix / Prime Video / YouTube. Disney+ will report
   itself as unsupported on Samsung — that is the app being honest,
   not a bug in your setup.

## If it does not connect

- "Could not connect to Samsung TV at 192.168.1.178:8002 / :8001":
  the TV is off, on a different Wi-Fi, or IP Remote is off. On the
  TV: Settings → General → Network → Expert Settings → turn on
  **IP Remote** (and, on some sets, **Power On with Mobile**).
- "Samsung TV refused the connection": the Allow prompt was denied,
  or the phone is blocked in the TV's Device Connection Manager
  (TV Settings → General → External Device Manager → Device
  Connection Manager → allow the phone).
- The app connects but a key does nothing: the WebSocket may have
  dropped — disconnect and connect again in the app.
- The app will not open at all: the 7-day signature expired — refresh
  it in SideStore (step 3, point 4).

## What changed in the code for this build

- `mobile/src/types.ts`: default control mode is now `direct`
  (was `backend`).
- `mobile/src/services/direct/samsungDirect.ts`: after a failed
  secure `wss://:8002` attempt, the client now tries plain
  `ws://:8001`, mirroring the Python backend adapter. An explicit
  "unauthorized" (Allow denied) is not retried.
- `mobile/app.json`: iOS bundle identifier
  `com.universalremote.UniversalSmartRemote` added (the workflow
  also passes it to `xcodebuild`).
- `mobile/package-lock.json`: added, so the cloud build installs
  exactly the same dependency versions every time.
- `.github/workflows/build-ios-unsigned-ipa.yml`: the free cloud
  build (new).
