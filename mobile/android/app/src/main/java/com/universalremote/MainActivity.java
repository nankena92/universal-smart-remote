package com.universalremote;

import com.facebook.react.ReactActivity;
import com.facebook.react.ReactActivityDelegate;
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint;
import com.facebook.react.defaults.DefaultReactActivityDelegate;

/**
 * Stock React Native 0.73 activity. The component name must match the
 * "name" field in mobile/app.json ("UniversalSmartRemote").
 */
public class MainActivity extends ReactActivity {

    @Override
    protected String getMainComponentName() {
        return "UniversalSmartRemote";
    }

    @Override
    protected ReactActivityDelegate createReactActivityDelegate() {
        return new DefaultReactActivityDelegate(
                this,
                getMainComponentName(),
                DefaultNewArchitectureEntryPoint.getFabricEnabled());
    }
}
