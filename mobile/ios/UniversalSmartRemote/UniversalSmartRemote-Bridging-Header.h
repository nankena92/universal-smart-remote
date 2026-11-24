// UniversalSmartRemote-Bridging-Header.h — Objective-C bridging header
// for the Swift native module.
//
// Exposes the React Native headers the Swift code subclasses/uses
// (RCTEventEmitter, RCTPromiseResolveBlock / RCTPromiseRejectBlock) to
// Swift. Set as the target's "Objective-C Bridging Header" build setting:
//   UniversalSmartRemote/UniversalSmartRemote-Bridging-Header.h
// (see ios/README.md — there is no .xcodeproj in this repo yet, so this
// setting is applied when the Xcode project is generated on a Mac).
#import <React/RCTBridgeModule.h>
#import <React/RCTEventEmitter.h>
