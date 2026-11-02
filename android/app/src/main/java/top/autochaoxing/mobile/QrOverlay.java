package top.autochaoxing.mobile;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.view.View;

final class QrOverlay extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private Rect bounds;
    QrOverlay(Context context) {
        super(context);
        paint.setColor(0xFF42E8A4);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(3 * getResources().getDisplayMetrics().density);
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
    }
    void update(Rect rectangle) {
        bounds = rectangle == null ? null : new Rect(rectangle);
        invalidate();
    }
    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (bounds != null) canvas.drawRoundRect(bounds.left, bounds.top, bounds.right, bounds.bottom, 14, 14, paint);
    }
}
