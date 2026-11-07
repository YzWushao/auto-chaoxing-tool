package top.autochaoxing.mobile;

import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Handler;
import android.provider.Settings;
import android.widget.Toast;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.core.content.FileProvider;
import org.json.JSONObject;
import javax.net.ssl.HttpsURLConnection;
import java.net.URL;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashSet;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Supplier;

/** Updates come only from the configured HTTPS origin and require user consent. */
final class AppUpdates {
    private final AppCompatActivity activity;
    private final Handler handler;
    private final Supplier<String> origin;
    private final Supplier<Boolean> foreground;
    private final ExecutorService io=Executors.newSingleThreadExecutor();
    private final ActivityResultLauncher<Intent> installPermission;
    private boolean checking,downloading;
    private AlertDialog prompt;
    private File ready;
    private String readyOrigin="";

    AppUpdates(AppCompatActivity activity,Handler handler,Supplier<String> origin,Supplier<Boolean> foreground) {
        this.activity=activity;this.handler=handler;this.origin=origin;this.foreground=foreground;
        installPermission=activity.registerForActivityResult(new ActivityResultContracts.StartActivityForResult(),result->{
            if(activity.getPackageManager().canRequestPackageInstalls())install();
            else {discard();toast("未允许安装更新，可在菜单中重新检查更新");}
        });
    }
    void check(boolean manual) {
        String base=origin.get();
        if(base.isEmpty()||checking||downloading||ready!=null||(prompt!=null&&prompt.isShowing()))return;
        checking=true;
        io.execute(()->{
            try {
                JSONObject meta=new JSONObject(new String(read(base+"/android/update.json",65536),java.nio.charset.StandardCharsets.UTF_8));
                int installed=activity.getPackageManager().getPackageInfo(activity.getPackageName(),0).versionCode;
                boolean newer=meta.optBoolean("available")&&meta.getInt("version_code")>installed;
                handler.post(()->{
                    checking=false;if(!valid(base))return;
                    if(!newer){if(manual)toast("当前已是最新版本");return;}
                    prompt=new AlertDialog.Builder(activity).setTitle("发现安卓新版本 "+meta.optString("version_name"))
                        .setMessage(meta.optString("notes","发现新版本，是否下载并安装？"))
                        .setNegativeButton("暂不更新",null).setPositiveButton("下载并安装",(d,w)->download(base,meta)).show();
                });
            } catch(Exception e){handler.post(()->{checking=false;if(manual&&valid(base))toast("检查更新失败，请稍后重试");});}
        });
    }
    private boolean valid(String base){return !activity.isFinishing()&&!activity.isDestroyed()&&foreground.get()&&base.equals(origin.get());}
    private HttpsURLConnection open(String address)throws Exception {
        HttpsURLConnection connection=(HttpsURLConnection)new URL(address).openConnection();
        connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(10000);connection.setReadTimeout(30000);
        connection.setUseCaches(false);
        if(connection.getResponseCode()!=200){connection.disconnect();throw new IllegalStateException();}
        return connection;
    }
    private byte[] read(String address,int limit)throws Exception {
        HttpsURLConnection connection=open(address);
        try(InputStream stream=connection.getInputStream();ByteArrayOutputStream output=new ByteArrayOutputStream()){
            byte[] buffer=new byte[4096];int count;
            while((count=stream.read(buffer))!=-1){if(output.size()+count>limit)throw new IllegalStateException();output.write(buffer,0,count);}
            return output.toByteArray();
        }finally{connection.disconnect();}
    }
    private void download(String base,JSONObject meta) {
        if(!valid(base)||downloading)return;
        downloading=true;toast("正在下载更新，完成后将请求系统安装");
        io.execute(()->{
            File file=null;
            try {
                long expected=meta.getLong("size");String hash=meta.getString("sha256");
                if(expected<=0||expected>104857600||!hash.matches("[a-f0-9]{64}"))throw new IllegalArgumentException();
                File directory=new File(activity.getCacheDir(),"updates");directory.mkdirs();
                file=File.createTempFile("update-",".apk",directory);
                HttpsURLConnection connection=open(base+"/android/latest.apk");
                MessageDigest digest=MessageDigest.getInstance("SHA-256");long total=0;
                try(InputStream input=connection.getInputStream();FileOutputStream output=new FileOutputStream(file)){
                    byte[] bytes=new byte[65536];int count;
                    while((count=input.read(bytes))!=-1){total+=count;if(total>expected)throw new IllegalStateException();digest.update(bytes,0,count);output.write(bytes,0,count);}
                }finally{connection.disconnect();}
                StringBuilder actual=new StringBuilder();for(byte value:digest.digest())actual.append(String.format(java.util.Locale.ROOT,"%02x",value&255));
                if(total!=expected||!actual.toString().equals(hash))throw new IllegalStateException();
                PackageManager pm=activity.getPackageManager();
                PackageInfo apk=pm.getPackageArchiveInfo(file.getAbsolutePath(),PackageManager.GET_SIGNATURES);
                PackageInfo current=pm.getPackageInfo(activity.getPackageName(),PackageManager.GET_SIGNATURES);
                if(apk==null||!activity.getPackageName().equals(apk.packageName)||apk.versionCode!=meta.getInt("version_code")
                    ||apk.versionCode<=current.versionCode||apk.signatures==null||current.signatures==null
                    ||!new HashSet<>(Arrays.asList(apk.signatures)).equals(new HashSet<>(Arrays.asList(current.signatures))))throw new IllegalStateException();
                File downloaded=file;
                handler.post(()->{
                    downloading=false;
                    if(!valid(base)){downloaded.delete();return;}
                    ready=downloaded;readyOrigin=base;
                    if(pm.canRequestPackageInstalls())install();
                    else new AlertDialog.Builder(activity).setTitle("允许安装更新")
                        .setMessage("请在系统页面允许本应用安装更新；授权后返回继续安装。")
                        .setNegativeButton("取消",(d,w)->discard()).setPositiveButton("去授权",(d,w)->{
                            try{installPermission.launch(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:"+activity.getPackageName())));}
                            catch(Exception e){discard();toast("无法打开安装授权设置");}
                        }).setOnCancelListener(d->discard()).show();
                });
            }catch(Exception e){if(file!=null)file.delete();handler.post(()->{downloading=false;if(valid(base))toast("下载或校验失败，未安装更新，请重试");});}
        });
    }
    private void install(){
        if(ready==null)return;
        if(!readyOrigin.equals(origin.get())){discard();return;}
        try {
            Uri uri=FileProvider.getUriForFile(activity,activity.getPackageName()+".updates",ready);
            activity.startActivity(new Intent(Intent.ACTION_VIEW).setDataAndType(uri,"application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION));
            ready=null;readyOrigin="";
        }catch(Exception e){discard();toast("无法启动系统安装器");}
    }
    private void discard(){if(ready!=null)ready.delete();ready=null;readyOrigin="";}
    private void toast(String text){Toast.makeText(activity,text,Toast.LENGTH_LONG).show();}
    void close(){io.shutdownNow();discard();if(prompt!=null)prompt.dismiss();}
}
