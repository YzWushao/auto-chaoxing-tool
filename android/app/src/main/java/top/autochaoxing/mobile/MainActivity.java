package top.autochaoxing.mobile;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Rect;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Size;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.PermissionRequest;
import android.webkit.GeolocationPermissions;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceError;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.PopupMenu;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.OnBackPressedCallback;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.resolutionselector.ResolutionSelector;
import androidx.camera.core.resolutionselector.ResolutionStrategy;
import androidx.camera.mlkit.vision.MlKitAnalyzer;
import androidx.camera.view.LifecycleCameraController;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.webkit.JavaScriptReplyProxy;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;

import com.google.mlkit.vision.barcode.BarcodeScanner;
import com.google.mlkit.vision.barcode.BarcodeScannerOptions;
import com.google.mlkit.vision.barcode.BarcodeScanning;
import com.google.mlkit.vision.barcode.ZoomSuggestionOptions;
import com.google.mlkit.vision.barcode.common.Barcode;

import org.json.JSONException;
import org.json.JSONObject;

import java.net.URI;
import javax.net.ssl.HttpsURLConnection;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Map;
import java.util.Collections;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends AppCompatActivity {
    private static final Set<String> ROUTES = new HashSet<>(Arrays.asList("overview", "study", "sign", "accounts", "settings"));
    private static final String[] PAGES = {"overview", "study", "sign", "accounts", "settings"};
    private static final String[] LABELS = {"总览", "刷课", "签到", "用户", "设置"};
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService analyzerExecutor = Executors.newSingleThreadExecutor();
    private final ExecutorService loginExecutor = Executors.newSingleThreadExecutor();
    private final Button[] tabs = new Button[5];
    private WebView web;
    private LinearLayout root, bottom, cameraPanel, loginPanel;
    private FrameLayout content;
    private EditText serverInput, usernameInput, passwordInput;
    private CheckBox remember;
    private Button loginButton;
    private TextView loginError;
    private boolean loggingIn;
    private TextView title, cameraStatus;
    private FrameLayout previewFrame;
    private PreviewView preview;
    private QrOverlay overlay;
    private CameraControls cameraControls;
    private LifecycleCameraController controller;
    private BarcodeScanner scanner;
    private int cameraGeneration;
    private String origin = "", scanId = "", latestQr = "";
    private long latestAt, interval = 100;
    private JavaScriptReplyProxy scanReply;
    private ValueCallback<Uri[]> fileCallback;
    private PermissionRequest webPermission;
    private boolean foreground, requestingCamera, resumeCamera;
    private boolean requestingLocation;
    private boolean resumeLocation, locationPermissionOnly;
    private GeolocationPermissions.Callback webLocationCallback;
    private String webLocationOrigin="";
    private String locationId="", locationOrigin="";
    private JavaScriptReplyProxy locationReply;
    private DeviceLocation deviceLocation;
    private AppUpdates updates;
    private final ActivityResultLauncher<String[]> locationPermission=registerForActivityResult(
        new ActivityResultContracts.RequestMultiplePermissions(), allowed -> {
            requestingLocation=false;
            boolean granted=hasLocationPermission();
            finishWebLocationPermission(granted);
            if(locationPermissionOnly){locationPermissionOnly=false;toast(granted?"定位权限已允许，可返回签到页使用设备位置":"未允许定位权限，可在应用权限设置中开启");}
            if(locationReply!=null){
                if(granted){resumeLocation=true;if(foreground)startDeviceLocation();}
                else cancelDeviceLocation("未允许定位权限，请在菜单中的定位权限与测试中处理");
            }
        });

    private final ActivityResultLauncher<String> cameraPermission = registerForActivityResult(
        new ActivityResultContracts.RequestPermission(), allowed -> {
            requestingCamera=false;
            if (webPermission != null) {
                if (allowed && trustedPage() && sameOrigin(webPermission.getOrigin())) webPermission.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
                else webPermission.deny();
                webPermission = null;
            } else if (!scanId.isEmpty()) {
                if (allowed && trustedPage()) {if(foreground)bindCamera();else resumeCamera=true;}
                else closeScanner("未允许摄像头权限，扫描已停止", true);
            }
        });
    private final ActivityResultLauncher<Intent> filePicker = registerForActivityResult(
        new ActivityResultContracts.StartActivityForResult(), result -> {
            if (fileCallback == null) return;
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result.getResultCode(), result.getData()));
            fileCallback = null;
        });
    private final Runnable report = new Runnable() {
        @Override public void run() {
            if (scanId.isEmpty()) return;
            String qr = SystemClock.elapsedRealtime() - latestAt < 750 ? latestQr : "";
            send("qr", qr);
            handler.postDelayed(this, interval);
        }
    };

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(0xFFF7F7FC);
        ViewCompat.setOnApplyWindowInsetsListener(root, (v, insets) -> {
            Insets padding = insets.getInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout());
            v.setPadding(padding.left, padding.top, padding.right, padding.bottom);
            return insets;
        });
        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        title = new TextView(this);title.setText("超星工具");title.setTextColor(0xFF29243E);title.setTextSize(17);title.setPadding(dp(16),0,0,0);
        toolbar.addView(title, new LinearLayout.LayoutParams(0, dp(48), 1));
        Button menu = button("⋮");menu.setContentDescription("连接与账户菜单");
        toolbar.addView(menu, new LinearLayout.LayoutParams(dp(54), dp(48)));
        menu.setOnClickListener(v -> showMenu(menu));root.addView(toolbar);
        createCameraPanel();
        web = new WebView(this);configureWeb();
        content=new FrameLayout(this);content.addView(web,new FrameLayout.LayoutParams(-1,-1));
        root.addView(content, new LinearLayout.LayoutParams(-1,0,1));
        createLoginPanel();
        bottom = new LinearLayout(this);bottom.setBackgroundColor(Color.WHITE);bottom.setVisibility(View.GONE);
        for (int i=0;i<PAGES.length;i++) {
            final String page=PAGES[i];tabs[i]=button(LABELS[i]);tabs[i].setTextSize(12);
            bottom.addView(tabs[i],new LinearLayout.LayoutParams(0,dp(58),1));
            tabs[i].setOnClickListener(v -> navigate(page));
        }
        root.addView(bottom);setContentView(root);
        getOnBackPressedDispatcher().addCallback(this,new OnBackPressedCallback(true) {
            @Override public void handleOnBackPressed() {
                if (!scanId.isEmpty()) { closeScanner("扫描已停止",true);return; }
                if (web.canGoBack()) web.goBack();
                else new AlertDialog.Builder(MainActivity.this).setMessage("退出超星工具？服务器已开始的任务会继续运行。")
                    .setNegativeButton("取消",null).setPositiveButton("退出",(d,w)->finish()).show();
            }
        });
        updates=new AppUpdates(this,handler,()->origin,()->foreground);
        String saved=getPreferences(MODE_PRIVATE).getString("server_origin","");
        if (!saved.isEmpty()&&getPreferences(MODE_PRIVATE).getBoolean("remember",false)) {
            if(connect(saved)){hideLogin();web.loadUrl(origin+"/");}else showLogin();
        } else {
            CookieManager.getInstance().removeAllCookies(null);
            showLogin();
        }
    }

    private Button button(String text) {
        Button button=new Button(this);button.setText(text);button.setAllCaps(false);
        button.setTextColor(0xFF605971);button.setBackgroundColor(Color.TRANSPARENT);
        button.setPadding(dp(2),0,dp(2),0);button.setMinWidth(0);button.setMinimumWidth(0);
        return button;
    }
    private int dp(int value) { return Math.round(value*getResources().getDisplayMetrics().density); }

    private void createLoginPanel() {
        android.widget.ScrollView scroll=new android.widget.ScrollView(this);scroll.setFillViewport(true);
        loginPanel=new LinearLayout(this);loginPanel.setOrientation(LinearLayout.VERTICAL);loginPanel.setGravity(Gravity.CENTER_VERTICAL);
        loginPanel.setPadding(dp(28),dp(24),dp(28),dp(32));loginPanel.setBackgroundColor(0xFFF7F7FC);
        TextView heading=new TextView(this);heading.setText("连接你的控制台");heading.setTextSize(27);heading.setTextColor(0xFF29243E);loginPanel.addView(heading);
        TextView note=new TextView(this);note.setText("填写项目服务器地址和管理员账号");note.setTextSize(14);note.setPadding(0,dp(12),0,dp(24));loginPanel.addView(note);
        serverInput=loginField("服务器地址","https://你的服务器:端口",android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_URI);
        usernameInput=loginField("用户名","项目管理员用户名",android.text.InputType.TYPE_CLASS_TEXT);
        passwordInput=loginField("密码","项目管理员密码",android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);
        passwordInput.setSaveEnabled(false);passwordInput.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        remember=new CheckBox(this);remember.setText("记住我");remember.setChecked(getPreferences(MODE_PRIVATE).getBoolean("remember",false));loginPanel.addView(remember);
        loginError=new TextView(this);loginError.setTextColor(0xFFB4445C);loginError.setPadding(0,dp(8),0,dp(8));loginPanel.addView(loginError);
        loginButton=button("连接并登录");loginButton.setTextColor(Color.WHITE);loginButton.setBackgroundColor(0xFF7055E8);
        loginPanel.addView(loginButton,new LinearLayout.LayoutParams(-1,dp(52)));loginButton.setOnClickListener(v->login());
        TextView footer=new TextView(this);footer.setText("记住我会保留登录会话，密码不会保存到本机。");footer.setTextSize(12);footer.setPadding(0,dp(20),0,0);loginPanel.addView(footer);
        if(remember.isChecked()) {
            serverInput.setText(getPreferences(MODE_PRIVATE).getString("server_origin",""));
            usernameInput.setText(getPreferences(MODE_PRIVATE).getString("username",""));
        }
        scroll.addView(loginPanel);content.addView(scroll,new FrameLayout.LayoutParams(-1,-1));
        loginPanel.setTag(scroll);
    }
    private EditText loginField(String label,String hint,int type) {
        TextView caption=new TextView(this);caption.setText(label);caption.setPadding(0,dp(10),0,dp(6));loginPanel.addView(caption);
        EditText input=new EditText(this);input.setSingleLine();input.setHint(hint);input.setInputType(type);input.setTextSize(15);
        loginPanel.addView(input,new LinearLayout.LayoutParams(-1,dp(52)));return input;
    }
    private void showLogin() {
        closeScanner("请登录控制台",true);bottom.setVisibility(View.GONE);
        if(loginPanel!=null){loginPanel.setVisibility(View.VISIBLE);((View)loginPanel.getTag()).setVisibility(View.VISIBLE);passwordInput.setText("");}
    }
    private void hideLogin(){loginPanel.setVisibility(View.GONE);((View)loginPanel.getTag()).setVisibility(View.GONE);}

    private void login() {
        if(loggingIn)return;
        String address=serverInput.getText().toString().trim(),username=usernameInput.getText().toString().trim(),password=passwordInput.getText().toString();
        if(username.isEmpty()||password.isEmpty()){loginError.setText("请填写用户名和密码");return;}
        if(!connect(address)){loginError.setText("请输入有效 HTTPS 服务器地址，不包含页面路径");return;}
        final String destination=origin;final boolean persist=remember.isChecked();
        loggingIn=true;loginButton.setEnabled(false);loginButton.setText("正在连接…");loginError.setText("");passwordInput.setText("");
        loginExecutor.execute(()->{
            try {
                java.net.CookieManager cookies=new java.net.CookieManager(null,java.net.CookiePolicy.ACCEPT_ORIGINAL_SERVER);
                JSONObject session=requestJson(destination,"/api/session",null,null,cookies);
                JSONObject credentials=new JSONObject().put("username",username).put("password",password);
                requestJson(destination,"/api/admin/login",credentials,session.getString("csrf"),cookies);
                List<String> headers=new ArrayList<>();
                for(java.net.HttpCookie cookie:cookies.getCookieStore().getCookies()) {
                    String value=cookie.getName()+"="+cookie.getValue()+"; Path=/; Secure; HttpOnly; SameSite=Lax";
                    if(persist&&cookie.getMaxAge()>0)value+="; Max-Age="+cookie.getMaxAge();
                    headers.add(value);
                }
                if(headers.isEmpty())throw new LoginFailure("服务器未返回有效登录会话");
                runOnUiThread(()->{
                    if(isFinishing()||isDestroyed())return;
                    var preferences=getPreferences(MODE_PRIVATE).edit().putBoolean("remember",persist);
                    if(persist)preferences.putString("server_origin",destination).putString("username",username);
                    else preferences.remove("server_origin").remove("username");preferences.apply();
                    CookieManager manager=CookieManager.getInstance();manager.removeAllCookies(removed->{
                        final int[] remaining={headers.size()};
                        for(String cookie:headers)manager.setCookie(destination,cookie,accepted->{
                            if(--remaining[0]==0){manager.flush();loggingIn=false;loginButton.setEnabled(true);loginButton.setText("连接并登录");hideLogin();web.loadUrl(destination+"/");}
                        });
                    });
                });
            } catch(Exception error) {
                runOnUiThread(()->{
                    if(isFinishing()||isDestroyed())return;
                    loggingIn=false;loginButton.setEnabled(true);loginButton.setText("连接并登录");
                    loginError.setText(error instanceof LoginFailure?error.getMessage():"连接失败，请检查地址、网络与 HTTPS 证书");
                });
            }
        });
    }
    private static class LoginFailure extends Exception { LoginFailure(String text){super(text);} }
    private JSONObject requestJson(String base,String path,JSONObject data,String csrf,java.net.CookieManager cookies) throws Exception {
        URI uri=URI.create(base+path);HttpsURLConnection connection=(HttpsURLConnection)uri.toURL().openConnection();
        connection.setConnectTimeout(12000);connection.setReadTimeout(12000);connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("Accept","application/json");connection.setRequestProperty("Origin",base);
        for(Map.Entry<String,List<String>> header:cookies.get(uri,Collections.emptyMap()).entrySet())connection.setRequestProperty(header.getKey(),String.join("; ",header.getValue()));
        try {
            if(data!=null){
                connection.setRequestMethod("POST");connection.setDoOutput(true);connection.setRequestProperty("Content-Type","application/json");
                connection.setRequestProperty("X-CSRF-Token",csrf);
                try(var output=connection.getOutputStream()){output.write(data.toString().getBytes(StandardCharsets.UTF_8));}
            }
            int status=connection.getResponseCode();cookies.put(uri,connection.getHeaderFields());
            try(InputStream input=status>=400?connection.getErrorStream():connection.getInputStream();ByteArrayOutputStream output=new ByteArrayOutputStream()) {
                if(input==null)throw new LoginFailure("服务器未返回登录结果");
                byte[] buffer=new byte[2048];int count;
                while((count=input.read(buffer))!=-1){output.write(buffer,0,count);if(output.size()>32768)throw new LoginFailure("服务器响应格式异常");}
                JSONObject result=new JSONObject(new String(output.toByteArray(),StandardCharsets.UTF_8));
                if(status!=200)throw new LoginFailure(status==401?"用户名或密码不正确":status==429?"登录尝试过多，请稍后再试":"登录失败，请检查服务器状态");
                return result;
            }
        }finally{connection.disconnect();}
    }

    private void createCameraPanel() {
        cameraPanel=new LinearLayout(this);cameraPanel.setOrientation(LinearLayout.VERTICAL);cameraPanel.setVisibility(View.GONE);
        previewFrame=new FrameLayout(this);preview=new PreviewView(this);preview.setScaleType(PreviewView.ScaleType.FILL_CENTER);
        overlay=new QrOverlay(this);previewFrame.addView(preview,new FrameLayout.LayoutParams(-1,-1));
        previewFrame.addView(overlay,new FrameLayout.LayoutParams(-1,-1));
        cameraPanel.addView(previewFrame,new LinearLayout.LayoutParams(-1,dp(210)));
        LinearLayout actions=new LinearLayout(this);actions.setGravity(Gravity.CENTER_VERTICAL);
        cameraStatus=new TextView(this);cameraStatus.setText("对准签到二维码 · 可点击对焦、双指缩放");cameraStatus.setTextSize(11);cameraStatus.setPadding(dp(12),0,0,0);
        actions.addView(cameraStatus,new LinearLayout.LayoutParams(0,dp(44),1));
        Button stop=button("停止");actions.addView(stop);stop.setOnClickListener(v->closeScanner("扫描已停止",true));
        cameraPanel.addView(actions);cameraControls=new CameraControls(this);cameraPanel.addView(cameraControls);root.addView(cameraPanel);
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void configureWeb() {
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setGeolocationEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.getSettings().setMixedContentMode(android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.getSettings().setMediaPlaybackRequiresUserGesture(true);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri=request.getUrl();
                if (sameOrigin(uri)) return false;
                if (!request.isForMainFrame()) return true;
                openExternal(uri);return true;
            }
            @Override public void onPageStarted(WebView view,String url,android.graphics.Bitmap favicon) {
                closeScanner("页面已切换，扫描已停止",true);bottom.setVisibility(View.GONE);
            }
            @Override public void onPageFinished(WebView view,String url) {
                if (trustedPage()) web.evaluateJavascript("document.documentElement.classList.add('android-native');",null);
            }
            @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error) {
                if (request.isForMainFrame()) {closeScanner("网络连接中断",true);title.setText("连接失败 · 菜单可重新配置");}
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onGeolocationPermissionsShowPrompt(String source,GeolocationPermissions.Callback callback){
                runOnUiThread(()->{
                    if(!foreground||!trustedPage()||!sameOrigin(Uri.parse(source))||webLocationCallback!=null||requestingLocation){callback.invoke(source,false,false);return;}
                    webLocationOrigin=source;webLocationCallback=callback;
                    if(hasLocationPermission())finishWebLocationPermission(true);
                    else requestLocationPermission();
                });
            }
            @Override public void onGeolocationPermissionsHidePrompt(){finishWebLocationPermission(false);}
            @Override public boolean onShowFileChooser(WebView view,ValueCallback<Uri[]> callback,FileChooserParams params) {
                if (!trustedPage()) return false;
                if (fileCallback!=null) fileCallback.onReceiveValue(null);
                fileCallback=callback;
                List<String> accepted=new ArrayList<>();
                for(String kind:params.getAcceptTypes()) {
                    if(kind.equals(".json"))accepted.add("application/json");
                    else if(kind.contains("/"))accepted.add(kind);
                }
                Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE);
                if(accepted.size()==1)intent.setType(accepted.get(0));
                else {intent.setType("*/*");if(!accepted.isEmpty())intent.putExtra(Intent.EXTRA_MIME_TYPES,accepted.toArray(new String[0]));}
                try { filePicker.launch(intent); } catch (ActivityNotFoundException e) { fileCallback.onReceiveValue(null);fileCallback=null; }
                return true;
            }
            @Override public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(()->{
                    if (!trustedPage()||!sameOrigin(request.getOrigin())||request.getResources().length!=1
                        ||!PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(request.getResources()[0])||!scanId.isEmpty()||webPermission!=null) {request.deny();return;}
                    webPermission=request;
                    requestingCamera=true;cameraPermission.launch(Manifest.permission.CAMERA);
                });
            }
            @Override public void onPermissionRequestCanceled(PermissionRequest request) { if (webPermission==request) webPermission=null; }
        });
    }

    private boolean connect(String address) {
        try {
            URI uri=new URI(address.trim());
            if (!"https".equalsIgnoreCase(uri.getScheme())||uri.getHost()==null||uri.getRawUserInfo()!=null
                ||uri.getQuery()!=null||uri.getFragment()!=null||!(uri.getPath()==null||uri.getPath().isEmpty()||uri.getPath().equals("/"))) throw new IllegalArgumentException();
            closeScanner("服务器已切换",true);
            if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
                if (!origin.isEmpty()) WebViewCompat.removeWebMessageListener(web,"AutoChaoxingNative");
                origin=new URI("https",null,uri.getHost().toLowerCase(java.util.Locale.ROOT),uri.getPort(),null,null,null).toString();
                WebViewCompat.addWebMessageListener(web,"AutoChaoxingNative",Collections.singleton(origin),
                    (view,message,source,isMainFrame,reply)->{
                        if (!isMainFrame||!sameOrigin(source)||!trustedPage()) return;
                        try { handleMessage(new JSONObject(message.getData()),reply); } catch (JSONException|IllegalArgumentException e) { toast("安卓请求格式无效"); }
                    });
            } else {
                origin=new URI("https",null,uri.getHost(),uri.getPort(),null,null,null).toString();
                toast("请更新 Android System WebView 以启用原生扫码");
            }
            title.setText("超星工具");handler.post(()->{if(updates!=null)updates.check(false);});return true;
        } catch (Exception e) { return false; }
    }

    private boolean sameOrigin(Uri uri) {
        if (origin.isEmpty()||uri==null) return false;
        Uri base=Uri.parse(origin);
        return "https".equalsIgnoreCase(uri.getScheme())&&base.getHost()!=null&&base.getHost().equalsIgnoreCase(uri.getHost())
            &&(base.getPort()==-1?443:base.getPort())==(uri.getPort()==-1?443:uri.getPort())&&uri.getUserInfo()==null;
    }
    private boolean trustedPage() {
        Uri current=Uri.parse(web.getUrl()==null?"":web.getUrl());
        return sameOrigin(current)&&("/".equals(current.getPath())||"/scan".equals(current.getPath()));
    }
    private void handleMessage(JSONObject data,JavaScriptReplyProxy reply) {
        switch (data.optString("type")) {
            case "capabilities":
                reply.postMessage("{\"type\":\"capabilities\",\"device_location\":true,\"app_version\":\"0.12.1\",\"version_code\":14}");break;
            case "device_location":
                if(!foreground||requestingLocation||!scanId.isEmpty()){
                    try{reply.postMessage(new JSONObject().put("type","device_location").put("id",data.optString("id")).put("error","请保持应用在前台，并停止当前扫描后重新定位").toString());}catch(JSONException ignored){ }
                    return;
                }
                cancelDeviceLocation("定位已取消");
                locationId=data.optString("id");if(!locationId.matches("location-[0-9]{1,10}")){locationId="";return;}
                locationReply=reply;locationOrigin=origin;
                if(hasLocationPermission())startDeviceLocation();
                else requestLocationPermission();
                break;
            case "cancel_location":cancelDeviceLocation("定位已取消");break;
            case "layout":
                if(data.optBoolean("authenticated"))hideLogin();
                else if("/".equals(Uri.parse(web.getUrl()).getPath())&&!loggingIn)showLogin();
                bottom.setVisibility(data.optBoolean("authenticated")?View.VISIBLE:View.GONE);
                String page=data.optString("route");
                for(int i=0;i<PAGES.length;i++) {
                    boolean selected=PAGES[i].equals(page)||(PAGES[i].equals("sign")&&page.startsWith("sign-"))
                        ||(PAGES[i].equals("study")&&page.equals("study-config"))||(PAGES[i].equals("settings")&&(page.equals("devices")||page.equals("presets")));
                    tabs[i].setTextColor(selected?0xFF7055E8:0xFF827A91);tabs[i].setBackgroundColor(selected?0xFFF0EDFC:Color.WHITE);
                }
                break;
            case "start":
                if (!foreground||webPermission!=null) return;
                closeScanner("旧扫描已停止",true);
                scanId=data.optString("id");if(!scanId.matches("[0-9]{1,10}")){scanId="";return;}
                interval=Math.min(10000,Math.max(100,data.optLong("interval",100)));scanReply=reply;
                if (ContextCompat.checkSelfPermission(this,Manifest.permission.CAMERA)==PackageManager.PERMISSION_GRANTED) bindCamera();
                else {requestingCamera=true;cameraPermission.launch(Manifest.permission.CAMERA);}
                break;
            case "stop": if (scanId.equals(data.optString("id"))) closeScanner("扫描已停止",false);break;
            case "interval": if(scanId.equals(data.optString("id")))interval=Math.min(10000,Math.max(100,data.optLong("interval",100)));break;
            default: break;
        }
    }

    private void bindCamera() {
        if (scanId.isEmpty()||!foreground) return;
        try {
            cameraPanel.setVisibility(View.VISIBLE);getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            int activeGeneration=++cameraGeneration;
            scanner=BarcodeScanning.getClient(new BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                .enableAllPotentialBarcodes().setZoomSuggestionOptions(new ZoomSuggestionOptions.Builder(
                    ratio->activeGeneration==cameraGeneration&&cameraControls.suggestZoom(ratio)).build()).build());
            controller=new LifecycleCameraController(this);controller.setCameraSelector(CameraSelector.DEFAULT_BACK_CAMERA);
            controller.setEnabledUseCases(LifecycleCameraController.IMAGE_ANALYSIS);controller.setTapToFocusEnabled(true);controller.setPinchToZoomEnabled(true);
            controller.setImageAnalysisResolutionSelector(new ResolutionSelector.Builder().setResolutionStrategy(
                new ResolutionStrategy(new Size(1920,1080),ResolutionStrategy.FALLBACK_RULE_CLOSEST_LOWER_THEN_HIGHER)).build());
            BarcodeScanner activeScanner=scanner;String activeId=scanId;
            controller.setImageAnalysisAnalyzer(analyzerExecutor,new MlKitAnalyzer(Collections.singletonList(scanner),
                ImageAnalysis.COORDINATE_SYSTEM_VIEW_REFERENCED,ContextCompat.getMainExecutor(this),result->{
                    if(!activeId.equals(scanId)||scanner!=activeScanner) return;
                    List<Barcode> codes=result.getValue(activeScanner);
                    if(codes==null||codes.isEmpty()) {latestQr="";overlay.update(null);cameraControls.detection(null,false);return;}
                    Barcode code=codes.get(0);
                    for(Barcode candidate:codes) if(isSignCode(candidate.getRawValue())) {code=candidate;break;}
                    Rect box=code.getBoundingBox();boolean decoded=code.getRawValue()!=null;
                    overlay.update(box,decoded);cameraControls.detection(box,decoded);
                    String raw=code.getRawValue();latestQr=isSignCode(raw)&&raw.length()<=4096?raw:"";latestAt=SystemClock.elapsedRealtime();
                    cameraStatus.setText(latestQr.isEmpty()?decoded?"已发现二维码，请对准签到二维码":
                        cameraControls.isSmart()?"发现疑似二维码 · 智能取景中":"发现疑似二维码 · 可手动放大或调焦":"已识别 · 服务器正在处理，请保持画面");
                }));
            preview.setController(controller);controller.bindToLifecycle(this);
            cameraControls.attach(controller,preview,this);
            send("started","");handler.post(report);
        } catch(Exception e) { closeScanner("无法启动相机，请检查权限或摄像头占用",true); }
    }
    private boolean isSignCode(String raw) {
        return raw!=null&&(raw.startsWith("SIGNIN:")||raw.contains("enc="));
    }
    private void send(String type,String value) {
        if(scanReply==null||scanId.isEmpty())return;
        try {
            JSONObject data=new JSONObject().put("type",type).put("id",scanId);
            if(type.equals("qr"))data.put("qr",value);else data.put("message",value);
            scanReply.postMessage(data.toString());
        } catch(JSONException|IllegalStateException ignored) { }
    }
    private void closeScanner(String message,boolean notify) {
        cancelDeviceLocation("定位已取消");
        finishWebLocationPermission(false);
        cameraGeneration++;
        if(notify)send("closed",message);
        handler.removeCallbacks(report);scanId="";scanReply=null;latestQr="";latestAt=0;
        resumeCamera=false;
        if(cameraControls!=null)cameraControls.detach();
        if(controller!=null){controller.clearImageAnalysisAnalyzer();controller.unbind();controller=null;}
        if(scanner!=null){scanner.close();scanner=null;}
        if(overlay!=null)overlay.update(null);
        if(cameraPanel!=null)cameraPanel.setVisibility(View.GONE);
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    private void navigate(String page) {
        if(!ROUTES.contains(page)||origin.isEmpty())return;
        closeScanner("页面已切换，扫描已停止",true);
        if(trustedPage()&&"/".equals(Uri.parse(web.getUrl()).getPath()))
            web.evaluateJavascript("location.hash="+JSONObject.quote(page)+";",null);
        else web.loadUrl(origin+"/#"+page);
    }
    private void showMenu(View anchor) {
        PopupMenu menu=new PopupMenu(this,anchor);
        menu.getMenu().add("连接服务器").setOnMenuItemClickListener(item->{configureServer();return true;});
        menu.getMenu().add("刷新页面").setOnMenuItemClickListener(item->{closeScanner("页面已刷新",true);web.reload();return true;});
        menu.getMenu().add("检查更新").setOnMenuItemClickListener(item->{if(updates!=null)updates.check(true);return true;});
        menu.getMenu().add("定位权限与测试").setOnMenuItemClickListener(item->{showLocationPermission();return true;});
        menu.getMenu().add("打开一次性扫码链接").setOnMenuItemClickListener(item->{openScanLink();return true;});
        menu.getMenu().add("退出控制台登录").setOnMenuItemClickListener(item->{
            closeScanner("已退出",true);if(trustedPage())web.evaluateJavascript("document.getElementById('logout')?.click();",null);return true;});
        menu.getMenu().add("关于与源码").setOnMenuItemClickListener(item->{new AlertDialog.Builder(this).setTitle("超星工具 0.12.1")
            .setMessage("安卓原生相机与 ML Kit 扫码，服务器统一执行任务。\nAGPL-3.0 · 扫码交互参考 ChaoxingSignFaker。")
            .setNegativeButton("关闭",null).setPositiveButton("源码",(d,w)->openExternal(Uri.parse("https://github.com/YzWushao/auto-chaoxing-tool"))).show();return true;});
        menu.show();
    }
    private void configureServer() {
        if(loggingIn)return;showLogin();serverInput.setText(origin);loginError.setText("");
    }
    private void openScanLink() {
        if(origin.isEmpty()){configureServer();return;}
        EditText input=new EditText(this);input.setHint("粘贴 QQ 中的一次性扫码链接");
        new AlertDialog.Builder(this).setTitle("打开扫码链接").setView(input).setNegativeButton("取消",null)
            .setPositiveButton("打开",(d,w)->{
                Uri uri=Uri.parse(input.getText().toString().trim());
                if(sameOrigin(uri)&&"/scan".equals(uri.getPath())&&uri.getFragment()!=null&&uri.getFragment().matches("[A-Za-z0-9_-]{43}"))web.loadUrl(uri.toString());
                else toast("请使用当前服务器签发的完整扫码链接");
            }).show();
    }
    private void openExternal(Uri uri) {
        if(!"http".equals(uri.getScheme())&&!"https".equals(uri.getScheme()))return;
        closeScanner("已离开扫码页面",true);
        try{startActivity(new Intent(Intent.ACTION_VIEW,uri));}catch(ActivityNotFoundException e){toast("没有可用的浏览器");}
    }
    private void toast(String text){Toast.makeText(this,text,Toast.LENGTH_LONG).show();}
    @Override protected void onResume(){super.onResume();foreground=true;if(web!=null)web.onResume();if(resumeLocation&&locationReply!=null)startDeviceLocation();if(resumeCamera&&!scanId.isEmpty()){resumeCamera=false;bindCamera();}if(updates!=null&&!requestingLocation)updates.check(false);}
    private void startDeviceLocation(){
        resumeLocation=false;
        if(locationReply==null||!foreground||!trustedPage()||!origin.equals(locationOrigin)){cancelDeviceLocation("页面已变化，请重新定位");return;}
        deviceLocation=new DeviceLocation(this,handler,fix->finishDeviceLocation(fix,""),error->finishDeviceLocation(null,error));deviceLocation.start();
    }
    private void finishDeviceLocation(JSONObject fix,String error){
        if(locationReply==null)return;
        if(trustedPage()&&(foreground||fix==null)&&origin.equals(locationOrigin))try {
            JSONObject message=new JSONObject().put("type","device_location").put("id",locationId);
            if(fix!=null)message.put("location",fix);else message.put("error",error);
            locationReply.postMessage(message.toString());
        } catch(Exception ignored){ }
        if(deviceLocation!=null)deviceLocation.cancel();deviceLocation=null;locationReply=null;locationId="";locationOrigin="";resumeLocation=false;
    }
    private void cancelDeviceLocation(String error){finishDeviceLocation(null,error);}
    private boolean hasLocationPermission(){return ContextCompat.checkSelfPermission(this,Manifest.permission.ACCESS_FINE_LOCATION)==PackageManager.PERMISSION_GRANTED
        ||ContextCompat.checkSelfPermission(this,Manifest.permission.ACCESS_COARSE_LOCATION)==PackageManager.PERMISSION_GRANTED;}
    private void requestLocationPermission(){
        requestingLocation=true;
        locationPermission.launch(new String[]{Manifest.permission.ACCESS_FINE_LOCATION,Manifest.permission.ACCESS_COARSE_LOCATION});
    }
    private void finishWebLocationPermission(boolean granted){
        if(webLocationCallback==null)return;
        GeolocationPermissions.Callback callback=webLocationCallback;String source=webLocationOrigin;
        webLocationCallback=null;webLocationOrigin="";
        callback.invoke(source,granted&&trustedPage()&&sameOrigin(Uri.parse(source)),false);
    }
    private void showLocationPermission(){
        String status=hasLocationPermission()?"已允许定位权限":"尚未允许定位权限";
        new AlertDialog.Builder(this).setTitle("定位权限与测试 · v0.12.1")
            .setMessage(status+"\n点击申请后会显示系统授权窗口；如已被永久拒绝，可进入应用权限设置。这里只检查权限，不上传位置。")
            .setNegativeButton("关闭",null).setNeutralButton("应用权限设置",(d,w)->{
                try{startActivity(new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.parse("package:"+getPackageName())));}catch(Exception e){toast("无法打开应用设置，请从系统设置进入");}
            }).setPositiveButton("申请定位权限",(d,w)->{
                if(hasLocationPermission()){toast("定位权限已允许，请检查系统位置服务是否开启");return;}
                if(requestingLocation){toast("正在等待系统定位授权");return;}
                locationPermissionOnly=true;requestLocationPermission();
            }).show();
    }
    @Override protected void onPause(){foreground=false;if(!requestingCamera&&!requestingLocation)closeScanner("应用已进入后台，扫描已停止",true);CookieManager.getInstance().flush();if(web!=null)web.onPause();super.onPause();}
    @Override protected void onDestroy(){
        if(updates!=null)updates.close();
        closeScanner("应用已关闭",false);handler.removeCallbacksAndMessages(null);analyzerExecutor.shutdown();loginExecutor.shutdown();
        if(fileCallback!=null)fileCallback.onReceiveValue(null);if(webPermission!=null)webPermission.deny();
        if(!getPreferences(MODE_PRIVATE).getBoolean("remember",false))CookieManager.getInstance().removeAllCookies(null);
        if(web!=null)web.destroy();super.onDestroy();
    }
}
