package com.sal0.voz;

import android.content.Context;
import android.content.pm.ActivityInfo;
import android.graphics.Bitmap;
import android.os.SystemClock;
import android.test.ActivityInstrumentationTestCase2;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebView;
import android.widget.Button;
import org.json.JSONArray;
import java.io.File;
import java.io.FileOutputStream;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** The real APK/WebView against a disposable FastAPI server, with no worker. */
@SuppressWarnings("deprecation")
public final class WebInterfaceTest extends ActivityInstrumentationTestCase2<MainActivity> {
    private WebView web;

    public WebInterfaceTest() { super(MainActivity.class); }

    @Override
    protected void setUp() throws Exception {
        super.setUp();
        Context context = getInstrumentation().getTargetContext();
        new ServerConfig("", "http://10.0.2.2:17870", "").save(context);
        context.getSharedPreferences("sal0_web_runtime", Context.MODE_PRIVATE)
            .edit().putInt("asset_cache_version", 301).commit();
        MainActivity activity = getActivity();
        getInstrumentation().runOnMainSync(() -> web = findWeb(activity.getWindow().getDecorView()));
        assertNotNull(web);
    }

    private WebView findWeb(View view) {
        if (view instanceof WebView) return (WebView) view;
        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;
            for (int i = 0; i < group.getChildCount(); i++) {
                WebView found = findWeb(group.getChildAt(i));
                if (found != null) return found;
            }
        }
        return null;
    }

    private String js(String expression) throws Exception {
        AtomicReference<String> result = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);
        getInstrumentation().runOnMainSync(() -> web.evaluateJavascript(
            "(function(){return (" + expression + ");})()", value -> { result.set(value); done.countDown(); }));
        assertTrue("WebView JS callback", done.await(5, TimeUnit.SECONDS));
        return result.get();
    }

    private void until(String expression) throws Exception {
        long deadline = SystemClock.uptimeMillis() + 25000;
        do {
            if ("true".equals(js(expression))) return;
            SystemClock.sleep(150);
        } while (SystemClock.uptimeMillis() < deadline);
        fail("WebView condition: " + expression + "; last result: " + js(expression));
    }

    private void tap(String selector) throws Exception {
        String query = "document.querySelector(" + org.json.JSONObject.quote(selector) + ")";
        until(query + "!==null");
        js("(" + query + ".scrollIntoView({block:'center',behavior:'instant'}),true)");
        getInstrumentation().waitForIdleSync();
        JSONArray rect = new JSONArray(js("(()=>{const r=" + query + ".getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2,innerWidth]})()"));
        int[] location = new int[2];
        getInstrumentation().runOnMainSync(() -> web.getLocationOnScreen(location));
        float scale = web.getWidth() / (float) rect.getDouble(2);
        float x = location[0] + (float) rect.getDouble(0) * scale;
        float y = location[1] + (float) rect.getDouble(1) * scale;
        long now = SystemClock.uptimeMillis();
        MotionEvent down = MotionEvent.obtain(now, now, MotionEvent.ACTION_DOWN, x, y, 0);
        MotionEvent up = MotionEvent.obtain(now, now + 80, MotionEvent.ACTION_UP, x, y, 0);
        getInstrumentation().sendPointerSync(down);
        getInstrumentation().sendPointerSync(up);
        down.recycle(); up.recycle();
        getInstrumentation().waitForIdleSync();
    }

    private void screenshot(String name) throws Exception {
        Bitmap bitmap = getInstrumentation().getUiAutomation().takeScreenshot();
        if (bitmap == null) return;
        File directory = getActivity().getExternalFilesDir(null);
        try (FileOutputStream file = new FileOutputStream(new File(directory, name + ".png"))) {
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, file);
        } finally { bitmap.recycle(); }
    }

    private Button findButton(View view, String label) {
        if (view instanceof Button && label.contentEquals(((Button) view).getText())) return (Button) view;
        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;
            for (int i = 0; i < group.getChildCount(); i++) {
                Button found = findButton(group.getChildAt(i), label);
                if (found != null) return found;
            }
        }
        return null;
    }

    public void testLibrarySettingsAndReloadOnActualWebView() throws Exception {
        until("document.querySelector('#auth')&&!document.querySelector('#auth').hidden");
        js("(document.querySelector('#password').value='android-ui-test-password',true)");
        tap("#auth-submit");
        until("document.querySelector('#server-status').textContent==='Conectado'");
        assertEquals(BuildConfig.VERSION_CODE, getActivity().getSharedPreferences("sal0_web_runtime", Context.MODE_PRIVATE).getInt("asset_cache_version", 0));
        assertEquals("true", js("new URL(document.querySelector('script[src]').src).searchParams.has('v')"));
        tap("#tab-library");
        until("document.querySelector('#library-results-pane').open");
        tap("#library-voices");
        tap("#add-voice");
        until("document.querySelector('#voice-dialog').open");
        screenshot("android-voice-dialog");
        tap("#close-voice-dialog");
        tap("#character-list .item-more>summary");
        tap("[data-character='22222222222222222222222222222222']");
        until("document.querySelector('#voice-dialog').open");
        js("(document.querySelector('#character-name').value='Voz editada no APK',true)");
        tap("#character-form button[type='submit']");
        until("!document.querySelector('#voice-dialog').open&&document.querySelector('#character-list').textContent.includes('Voz editada no APK')");
        tap("[data-preview='voice-22222222222222222222222222222222']");
        until("!document.querySelector('#preview-voice-22222222222222222222222222222222').hidden");
        tap("[data-preview='voice-22222222222222222222222222222222']");
        tap("[data-selection-start='characters']");
        tap("[data-select-all='characters']");
        tap("[data-delete-selected='characters']");
        until("document.querySelector('#delete-dialog').open");
        tap("#delete-cancel");
        tap("[data-clear-selection='characters']");
        tap("[data-use-voice='22222222222222222222222222222222']");
        until("!document.querySelector('#view-create').hidden&&document.querySelector('#character').value==='22222222222222222222222222222222'");
        screenshot("android-create");
        tap("#tab-settings");
        tap(".settings-section:nth-of-type(2)>summary");
        until("document.querySelector('#telegram-token').offsetHeight>0");
        js("(document.querySelector('#telegram-token').value='preserved-draft',true)");
        tap("#collapse-settings");
        assertEquals("true", js("document.querySelector('#telegram-token').value==='preserved-draft'&&document.querySelectorAll('.settings-section[open]').length===0"));
        screenshot("android-settings");
        tap("#tab-library");
        tap("[data-open-result='33333333333333333333333333333333']");
        until("!document.querySelector('#current-result').hidden");
        assertEquals("true", js("document.querySelector('#current-result audio')!==null"));
        screenshot("android-result");
        getInstrumentation().runOnMainSync(() -> getActivity().setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE));
        until("innerWidth>innerHeight");
        assertEquals("true", js("document.documentElement.scrollWidth<=innerWidth"));
        screenshot("android-landscape");
        Button reload = findButton(getActivity().getWindow().getDecorView(), "Recarregar");
        assertNotNull(reload);
        String oldUrl = js("location.href");
        getInstrumentation().runOnMainSync(reload::performClick);
        until("location.href!==" + oldUrl + "&&document.querySelector('#server-status')&&document.querySelector('#server-status').textContent==='Conectado'");
        assertEquals("true", js("document.querySelector('#auth').hidden"));
        tap("#tab-library");tap("#library-voices");
        until("document.querySelector('#character-list').textContent.includes('Voz editada no APK')");
    }
}
