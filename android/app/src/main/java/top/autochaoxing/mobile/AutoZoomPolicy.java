package top.autochaoxing.mobile;

/** Timing and hardware bounds for native ML Kit zoom suggestions. */
final class AutoZoomPolicy {
    private boolean enabled=true;
    private long adjustedAt=-800, decodedUntil, candidateAt;

    void setEnabled(boolean value,long now) {
        enabled=value;adjustedAt=now-800;decodedUntil=0;candidateAt=now;
    }
    void observe(boolean candidate,boolean decoded,long now) {
        if(candidate)candidateAt=now;
        if(decoded)decodedUntil=now+1500;
    }
    float suggest(float requested,float current,float minimum,float maximum,long now) {
        if(!enabled||!validRange(current,minimum,maximum)||!Float.isFinite(requested)||requested<=0
            ||now<decodedUntil||now-adjustedAt<800)return Float.NaN;
        float ratio=Math.max(minimum,Math.min(requested,maximum));
        if(Math.abs(ratio-current)<.05f)return Float.NaN;
        adjustedAt=now;return ratio;
    }
    float resetIfLost(float current,float minimum,float maximum,long now) {
        if(!enabled||!validRange(current,minimum,maximum)||now-candidateAt<=4000||now-adjustedAt<=4000||current<=1.1f)return Float.NaN;
        adjustedAt=now;return Math.max(minimum,Math.min(1f,maximum));
    }
    private boolean validRange(float current,float minimum,float maximum) {
        return Float.isFinite(current)&&Float.isFinite(minimum)&&Float.isFinite(maximum)&&current>0&&minimum>0&&maximum>=minimum;
    }
}
