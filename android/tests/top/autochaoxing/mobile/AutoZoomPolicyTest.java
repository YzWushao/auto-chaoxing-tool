package top.autochaoxing.mobile;

public final class AutoZoomPolicyTest {
    private static void same(float expected,float actual){if(Math.abs(expected-actual)>.001f||Float.isNaN(actual))throw new AssertionError("Expected "+expected+", got "+actual);}
    private static void rejected(float value){if(!Float.isNaN(value))throw new AssertionError("Unexpected zoom command: "+value);}
    public static void main(String[] args) {
        AutoZoomPolicy p=new AutoZoomPolicy();p.setEnabled(true,1000);
        same(8,p.suggest(100,1,.5f,8,1000));
        rejected(p.suggest(3,8,.5f,8,1799));
        same(.5f,p.suggest(.1f,8,.5f,8,1800));
        p.observe(true,true,2000);
        rejected(p.suggest(4,1,1,8,3499));
        same(4,p.suggest(4,1,1,8,3500));
        p.setEnabled(false,4000);
        rejected(p.suggest(8,1,1,8,5000));rejected(p.resetIfLost(8,1,8,10000));
        p.setEnabled(true,11000);
        same(2,p.suggest(2,1,1,8,11000));
        p.observe(true,false,12000);rejected(p.resetIfLost(2,1,8,16000));
        same(1,p.resetIfLost(2,1,8,16001));
        rejected(p.resetIfLost(2,1,8,16002));
        p.setEnabled(true,20000);
        for(float bad:new float[]{Float.NaN,Float.POSITIVE_INFINITY,Float.NEGATIVE_INFINITY,0,-1})rejected(p.suggest(bad,1,1,8,20000));
        rejected(p.suggest(2,1,8,1,20000));rejected(p.suggest(2,Float.NaN,1,8,20000));
        rejected(p.suggest(1.01f,1,1,8,20000));same(2,p.suggest(2,1,1,8,20000));
        p.setEnabled(true,30000);same(2,p.resetIfLost(5,2,8,35001));
        System.out.println("Auto zoom hardware bounds, manual override, decode hold, rate limit and lost-target reset passed");
    }
}
