package top.autochaoxing.mobile;

import android.annotation.SuppressLint;
import android.content.Context;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.SystemClock;
import org.json.JSONObject;
import java.util.function.Consumer;

/** One foreground fix, no cached coordinates and no Google Play Services dependency. */
final class DeviceLocation implements LocationListener {
    private final LocationManager manager;
    private final Handler handler;
    private final Consumer<JSONObject> success;
    private final Consumer<String> failure;
    private Location best;
    private boolean active;
    private final Runnable deadline = () -> finish();

    DeviceLocation(Context context, Handler handler, Consumer<JSONObject> success, Consumer<String> failure) {
        manager=(LocationManager)context.getSystemService(Context.LOCATION_SERVICE);
        this.handler=handler;this.success=success;this.failure=failure;
    }
    @SuppressLint("MissingPermission") void start() {
        active=true;int count=0;
        for(String provider:new String[]{LocationManager.GPS_PROVIDER,LocationManager.NETWORK_PROVIDER}) {
            try {
                if(manager.isProviderEnabled(provider)) {
                    manager.requestLocationUpdates(provider,1000,0,this,handler.getLooper());count++;
                }
            } catch(SecurityException|IllegalArgumentException ignored) { }
        }
        if(count==0){cancel();failure.accept("无法定位，请开启系统位置服务并允许定位权限");return;}
        handler.postDelayed(deadline,20000);
    }
    @Override public void onLocationChanged(Location location) {
        long age=SystemClock.elapsedRealtimeNanos()-location.getElapsedRealtimeNanos();
        if(!active||!location.hasAccuracy()||location.getAccuracy()<=0||age<0||age>10000000000L)return;
        if(best==null||location.getAccuracy()<best.getAccuracy())best=new Location(location);
        if(best.getAccuracy()<=30)finish();
    }
    private void finish() {
        if(!active)return;
        Location result=best;cancel();
        if(result==null){failure.accept("定位超时，请到信号较好的位置后重试");return;}
        try {
            success.accept(new JSONObject().put("latitude",result.getLatitude()).put("longitude",result.getLongitude())
                .put("accuracy",result.getAccuracy()).put("captured_at",result.getTime()/1000.0));
        } catch(Exception e){failure.accept("设备定位结果无效，请重新获取");}
    }
    void cancel(){active=false;handler.removeCallbacks(deadline);try{manager.removeUpdates(this);}catch(SecurityException ignored){ }best=null;}
    @Override public void onProviderEnabled(String provider) { }
    @Override public void onProviderDisabled(String provider) { }
    @Override public void onStatusChanged(String provider,int status,Bundle extras) { }
}
