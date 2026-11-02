package top.autochaoxing.mobile;

import android.content.Context;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CaptureRequest;
import android.graphics.Rect;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.TextView;

import androidx.appcompat.widget.SwitchCompat;
import androidx.camera.camera2.interop.Camera2CameraControl;
import androidx.camera.camera2.interop.Camera2CameraInfo;
import androidx.camera.camera2.interop.CaptureRequestOptions;
import androidx.camera.core.FocusMeteringAction;
import androidx.camera.core.ZoomState;
import androidx.camera.view.LifecycleCameraController;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;
import androidx.lifecycle.LifecycleOwner;
import androidx.lifecycle.Observer;

import com.google.common.util.concurrent.ListenableFuture;
import java.util.Locale;
import java.util.concurrent.CancellationException;
import java.util.concurrent.TimeUnit;

/** Native controls operate the analysis camera as well as its preview. */
final class CameraControls extends LinearLayout {
    private final TextView zoomLabel, focusLabel;
    private final SeekBar zoomBar, focusBar;
    private final SwitchCompat manual;
    private final Button resetZoom, refocus, smartButton, manualButton;
    private final TextView modeLabel;
    private LifecycleCameraController camera;
    private PreviewView preview;
    private Camera2CameraControl interop;
    private float nearest;
    private int generation, focusRequest;
    private boolean changing, zoomDragging;
    private boolean smart=true;
    private final AutoZoomPolicy zoomPolicy=new AutoZoomPolicy();
    private long focusedAt;
    private Observer<ZoomState> zoomObserver;
    private Observer<Integer> focusObserver;

    CameraControls(Context context) {
        super(context);setOrientation(VERTICAL);setPadding(dp(12),0,dp(12),dp(4));
        LinearLayout modeRow=new LinearLayout(context);
        smartButton=button("智能取景");manualButton=button("手动调整");
        modeRow.addView(smartButton,new LayoutParams(0,dp(38),1));modeRow.addView(manualButton,new LayoutParams(0,dp(38),1));addView(modeRow);
        modeLabel=label("模型寻找疑似二维码并建议放大倍率");addView(modeLabel);
        smartButton.setOnClickListener(v->setSmart(true));manualButton.setOnClickListener(v->setSmart(false));
        LinearLayout zoomRow=new LinearLayout(context);zoomRow.setGravity(Gravity.CENTER_VERTICAL);
        zoomLabel=label("变焦 · 正在读取相机");zoomRow.addView(zoomLabel,new LayoutParams(0,dp(34),1));
        resetZoom=button("1×");zoomRow.addView(resetZoom,new LayoutParams(dp(48),dp(36)));addView(zoomRow);
        zoomBar=new SeekBar(context);zoomBar.setMax(1000);zoomBar.setEnabled(false);
        zoomBar.setContentDescription("相机变焦倍率");addView(zoomBar,new LayoutParams(-1,dp(34)));
        LinearLayout focusRow=new LinearLayout(context);focusRow.setGravity(Gravity.CENTER_VERTICAL);
        manual=new SwitchCompat(context);manual.setText("手动对焦");manual.setTextSize(12);manual.setEnabled(false);
        focusRow.addView(manual,new LayoutParams(0,dp(38),1));refocus=button("重新对焦");
        focusRow.addView(refocus,new LayoutParams(dp(94),dp(38)));addView(focusRow);
        focusLabel=label("自动对焦 · 点击画面选择对焦点");addView(focusLabel);
        focusBar=new SeekBar(context);focusBar.setMax(1000);focusBar.setProgress(250);focusBar.setVisibility(GONE);
        focusBar.setContentDescription("手动对焦位置，左侧远、右侧近");addView(focusBar,new LayoutParams(-1,dp(34)));
        zoomBar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener(){
            public void onProgressChanged(SeekBar bar,int value,boolean user){
                if(user&&camera!=null&&!smart)camera.setLinearZoom(value/1000f);
            }
            public void onStartTrackingTouch(SeekBar bar){zoomDragging=true;}
            public void onStopTrackingTouch(SeekBar bar){zoomDragging=false;updateZoom(camera==null?null:camera.getZoomState().getValue());}
        });
        focusBar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener(){
            public void onProgressChanged(SeekBar bar,int value,boolean user){if(user&&manual.isChecked())applyFocus();}
            public void onStartTrackingTouch(SeekBar bar){}
            public void onStopTrackingTouch(SeekBar bar){}
        });
        manual.setOnCheckedChangeListener((button,checked)->{if(!changing)applyFocus();});
        resetZoom.setOnClickListener(v->{
            if(camera==null)return;setSmart(false);ZoomState state=camera.getZoomState().getValue();
            if(state!=null)camera.setZoomRatio(Math.max(state.getMinZoomRatio(),Math.min(1f,state.getMaxZoomRatio())));
        });
        refocus.setOnClickListener(v->{
            if(camera==null||preview==null)return;
            if(manual.isChecked())manual.setChecked(false);
            else resetAutofocus();
            var point=preview.getMeteringPointFactory().createPoint(preview.getWidth()/2f,preview.getHeight()/2f);
            camera.getCameraControl().startFocusAndMetering(new FocusMeteringAction.Builder(point,FocusMeteringAction.FLAG_AF)
                .setAutoCancelDuration(5,TimeUnit.SECONDS).build());
        });
        resetZoom.setEnabled(false);refocus.setEnabled(false);
        updateMode();
    }

    void attach(LifecycleCameraController value,PreviewView view,LifecycleOwner owner) {
        detach();camera=value;preview=view;int active=++generation;
        preview.setOnTouchListener((v,event)->{
            if(event.getPointerCount()>1&&event.getActionMasked()==MotionEvent.ACTION_MOVE&&smart)setSmart(false);
            return false;
        });
        value.getInitializationFuture().addListener(()->{
            if(camera!=value||generation!=active)return;
            try {
                value.getInitializationFuture().get();
                if(value.getCameraInfo()==null||value.getCameraControl()==null)return;
                zoomObserver=this::updateZoom;value.getZoomState().observe(owner,zoomObserver);
                focusObserver=status->{
                    if(manual.isChecked())return;
                    focusLabel.setText(status==LifecycleCameraController.TAP_TO_FOCUS_STARTED?"自动对焦中…":
                        status==LifecycleCameraController.TAP_TO_FOCUS_FOCUSED?"已对焦 · 可点击画面重新选择":
                        status==LifecycleCameraController.TAP_TO_FOCUS_NOT_FOCUSED||status==LifecycleCameraController.TAP_TO_FOCUS_FAILED?
                            "暂未对上焦 · 可点按重试或切换手动":"自动对焦 · 点击画面选择对焦点");
                };
                value.getTapToFocusState().observe(owner,focusObserver);refocus.setEnabled(true);
                var info=Camera2CameraInfo.from(value.getCameraInfo());
                Float minimum=info.getCameraCharacteristic(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE);
                int[] modes=info.getCameraCharacteristic(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES);
                boolean off=false;if(modes!=null)for(int mode:modes)off|=mode==CaptureRequest.CONTROL_AF_MODE_OFF;
                nearest=minimum!=null&&Float.isFinite(minimum)?minimum:0;
                if(nearest>0&&off){interop=Camera2CameraControl.from(value.getCameraControl());manual.setEnabled(!smart);}
                else manual.setText("手动对焦（设备不支持）");
                updateMode();
            }catch(InterruptedException e){Thread.currentThread().interrupt();}
            catch(Exception e){focusLabel.setText("可点击画面对焦，当前设备未提供手动调焦接口");}
        },ContextCompat.getMainExecutor(getContext()));
    }

    private void updateZoom(ZoomState state) {
        if(camera==null||state==null)return;
        boolean available=state.getMaxZoomRatio()>state.getMinZoomRatio();
        zoomBar.setEnabled(available&&!smart);resetZoom.setEnabled(available);
        zoomLabel.setText(String.format(Locale.ROOT,"变焦 %.1f×  ·  %.1f–%.1f×",state.getZoomRatio(),state.getMinZoomRatio(),state.getMaxZoomRatio()));
        if(!zoomDragging)zoomBar.setProgress(Math.round(state.getLinearZoom()*1000));
    }

    private void applyFocus() {
        if(camera==null||interop==null||smart)return;
        if(!manual.isChecked()){resetAutofocus();return;}
        camera.setTapToFocusEnabled(false);focusBar.setVisibility(VISIBLE);
        focusLabel.setText("远 ← 对焦位置 "+Math.round(focusBar.getProgress()/10f)+"% → 近");
        var options=new CaptureRequestOptions.Builder().setCaptureRequestOption(CaptureRequest.CONTROL_AF_MODE,CaptureRequest.CONTROL_AF_MODE_OFF)
            .setCaptureRequestOption(CaptureRequest.LENS_FOCUS_DISTANCE,nearest*focusBar.getProgress()/1000f).build();
        int request=++focusRequest,active=generation;
        ListenableFuture<Void> task=interop.setCaptureRequestOptions(options);
        task.addListener(()->{
            if(active!=generation||request!=focusRequest||camera==null)return;
            try{task.get();}
            catch(InterruptedException e){Thread.currentThread().interrupt();}
            catch(CancellationException e){}
            catch(Exception e){
                changing=true;manual.setChecked(false);changing=false;resetAutofocus();
                focusLabel.setText("手动调焦未生效，已恢复自动对焦");
            }
        },ContextCompat.getMainExecutor(getContext()));
    }

    boolean isSmart(){return smart;}

    private void setSmart(boolean enabled) {
        smart=enabled;zoomPolicy.setEnabled(enabled,SystemClock.elapsedRealtime());
        if(enabled&&manual.isChecked()){changing=true;manual.setChecked(false);changing=false;resetAutofocus();}
        updateMode();
    }

    private void updateMode() {
        smartButton.setTextColor(smart?0xFF7055E8:0xFF777080);manualButton.setTextColor(smart?0xFF777080:0xFF7055E8);
        smartButton.setBackgroundColor(smart?0xFFEDE8FC:0xFFF7F7FC);manualButton.setBackgroundColor(smart?0xFFF7F7FC:0xFFEDE8FC);
        modeLabel.setText(smart?"模型寻找黄色框区域，自动放大并对焦；请将二维码移至中央":"手动调整倍率；可点按对焦，或启用下方手动对焦");
        manual.setEnabled(!smart&&interop!=null&&nearest>0);
        if(camera!=null)updateZoom(camera.getZoomState().getValue());
    }

    boolean suggestZoom(float requested) {
        if(!smart||camera==null||!Float.isFinite(requested)||requested<=0)return false;
        long now=SystemClock.elapsedRealtime();
        ZoomState state=camera.getZoomState().getValue();if(state==null)return false;
        float ratio=zoomPolicy.suggest(requested,state.getZoomRatio(),state.getMinZoomRatio(),state.getMaxZoomRatio(),now);
        if(Float.isNaN(ratio))return false;
        camera.setZoomRatio(ratio);return true;
    }

    void detection(Rect rectangle,boolean decoded) {
        if(camera==null)return;long now=SystemClock.elapsedRealtime();
        zoomPolicy.observe(rectangle!=null,decoded,now);
        if(rectangle!=null){
            if(smart&&!decoded&&preview!=null&&now-focusedAt>2500&&preview.getWidth()>0&&preview.getHeight()>0){
                focusedAt=now;
                var point=preview.getMeteringPointFactory().createPoint(rectangle.exactCenterX(),rectangle.exactCenterY());
                camera.getCameraControl().startFocusAndMetering(new FocusMeteringAction.Builder(point,FocusMeteringAction.FLAG_AF)
                    .setAutoCancelDuration(3,TimeUnit.SECONDS).build());
            }
        }else if(smart){
            ZoomState state=camera.getZoomState().getValue();
            if(state!=null){float ratio=zoomPolicy.resetIfLost(state.getZoomRatio(),state.getMinZoomRatio(),state.getMaxZoomRatio(),now);if(!Float.isNaN(ratio))camera.setZoomRatio(ratio);}
        }
    }

    private void resetAutofocus() {
        focusRequest++;focusBar.setVisibility(GONE);
        focusLabel.setText("自动对焦 · 点击画面选择对焦点");
        if(interop!=null)interop.clearCaptureRequestOptions();
        if(camera!=null)camera.setTapToFocusEnabled(true);
    }

    void detach() {
        generation++;focusRequest++;
        if(camera!=null){
            if(zoomObserver!=null)camera.getZoomState().removeObserver(zoomObserver);
            if(focusObserver!=null)camera.getTapToFocusState().removeObserver(focusObserver);
        }
        if(preview!=null)preview.setOnTouchListener(null);
        camera=null;preview=null;interop=null;nearest=0;zoomObserver=null;focusObserver=null;zoomDragging=false;
        smart=true;focusedAt=0;zoomPolicy.setEnabled(true,SystemClock.elapsedRealtime());
        changing=true;manual.setChecked(false);changing=false;manual.setEnabled(false);manual.setText("手动对焦");
        zoomBar.setEnabled(false);resetZoom.setEnabled(false);refocus.setEnabled(false);focusBar.setVisibility(GONE);
        updateMode();
    }

    private int dp(int value){return Math.round(value*getResources().getDisplayMetrics().density);}
    private TextView label(String text){TextView v=new TextView(getContext());v.setText(text);v.setTextSize(11);v.setGravity(Gravity.CENTER_VERTICAL);return v;}
    private Button button(String text){Button v=new Button(getContext());v.setText(text);v.setAllCaps(false);v.setTextSize(11);v.setMinWidth(0);v.setMinimumWidth(0);v.setPadding(0,0,0,0);return v;}
}
