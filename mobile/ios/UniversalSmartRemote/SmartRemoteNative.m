// SmartRemoteNative.m — Objective-C externs exposing the Swift
// SmartRemoteNative module to React Native (CONTRACTS.md §3).
//
// The implementation lives in SmartRemoteNative.swift. This file only
// declares the methods React Native may call; the Swift class is exposed
// to Objective-C with @objc(SmartRemoteNative), and the method signatures
// here must match the Swift @objc methods exactly:
//   getNetworkInfo(_:rejecter:), isWifiConnected(_:rejecter:),
//   startDiscovery(_:rejecter:), stopDiscovery(_:rejecter:).
#import <React/RCTBridgeModule.h>
#import <React/RCTEventEmitter.h>

@interface RCT_EXTERN_MODULE(SmartRemoteNative, RCTEventEmitter)

RCT_EXTERN_METHOD(getNetworkInfo:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject)

RCT_EXTERN_METHOD(isWifiConnected:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject)

RCT_EXTERN_METHOD(startDiscovery:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject)

RCT_EXTERN_METHOD(stopDiscovery:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject)

@end
