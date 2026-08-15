package pixi.recomp;

import java.io.File;
import java.io.FileOutputStream;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Sidecar loaded into a debuggable process via JDWP + DexClassLoader.
 * Not part of the Android app source.
 */
public final class RecompAgent implements InvocationHandler {
  private static final ConcurrentHashMap<String, AtomicLong> COUNTS =
      new ConcurrentHashMap<String, AtomicLong>();
  private static final AtomicBoolean ENABLED = new AtomicBoolean(false);
  private static File snapshot;
  private static File cmdFile;
  private static Thread writer;

  public static void install() throws Exception {
    Class<?> composerKt = Class.forName("androidx.compose.runtime.ComposerKt");
    Class<?> tracerIface = Class.forName("androidx.compose.runtime.CompositionTracer");
    Object tracer =
        Proxy.newProxyInstance(
            tracerIface.getClassLoader(), new Class[] {tracerIface}, new RecompAgent());
    Field field = composerKt.getDeclaredField("compositionTracer");
    field.setAccessible(true);
    field.set(null, tracer);

    Class<?> at = Class.forName("android.app.ActivityThread");
    Object app = at.getMethod("currentApplication").invoke(null);
    File cache = (File) app.getClass().getMethod("getCacheDir").invoke(app);
    snapshot = new File(cache, "pixi_recomp.tsv");
    cmdFile = new File(cache, "pixi_recomp.cmd");
    ENABLED.set(true);
    startWriter();
  }

  public static void setEnabled(boolean on) {
    ENABLED.set(on);
  }

  public static void reset() {
    COUNTS.clear();
  }

  @Override
  public Object invoke(Object proxy, Method method, Object[] args) {
    String name = method.getName();
    if ("isTraceInProgress".equals(name)) {
      return Boolean.valueOf(ENABLED.get());
    }
    if ("traceEventStart".equals(name) && args != null && args.length > 0) {
      Object last = args[args.length - 1];
      if (ENABLED.get() && last instanceof String && ((String) last).length() > 0) {
        String key = (String) last;
        AtomicLong c = COUNTS.get(key);
        if (c == null) {
          AtomicLong created = new AtomicLong(0);
          AtomicLong prev = COUNTS.putIfAbsent(key, created);
          c = prev != null ? prev : created;
        }
        c.incrementAndGet();
      }
      return null;
    }
    if ("equals".equals(name)) {
      return Boolean.valueOf(proxy == args[0]);
    }
    if ("hashCode".equals(name)) {
      return Integer.valueOf(System.identityHashCode(proxy));
    }
    if ("toString".equals(name)) {
      return "pixi.recomp.RecompAgent";
    }
    return null;
  }

  private static void startWriter() {
    if (writer != null) {
      return;
    }
    writer =
        new Thread(
            new Runnable() {
              @Override
              public void run() {
                while (!Thread.currentThread().isInterrupted()) {
                  try {
                    Thread.sleep(200L);
                  } catch (InterruptedException e) {
                    return;
                  }
                  applyCmd();
                  if (ENABLED.get()) {
                    writeSnapshot();
                  }
                }
              }
            },
            "pixi-recomp");
    writer.setDaemon(true);
    writer.start();
  }

  private static void applyCmd() {
    if (cmdFile == null || !cmdFile.exists()) {
      return;
    }
    try {
      java.io.FileInputStream in = new java.io.FileInputStream(cmdFile);
      byte[] buf = new byte[32];
      int n = in.read(buf);
      in.close();
      cmdFile.delete();
      if (n <= 0) {
        return;
      }
      String cmd = new String(buf, 0, n, StandardCharsets.UTF_8).trim();
      if ("reset".equals(cmd) || "clear".equals(cmd)) {
        reset();
      } else if ("off".equals(cmd) || "stop".equals(cmd)) {
        ENABLED.set(false);
      } else if ("on".equals(cmd) || "start".equals(cmd)) {
        ENABLED.set(true);
      }
    } catch (Exception ignored) {
    }
  }

  private static void writeSnapshot() {
    if (snapshot == null) {
      return;
    }
    ArrayList<Map.Entry<String, AtomicLong>> rows =
        new ArrayList<Map.Entry<String, AtomicLong>>(COUNTS.entrySet());
    Collections.sort(
        rows,
        new Comparator<Map.Entry<String, AtomicLong>>() {
          @Override
          public int compare(Map.Entry<String, AtomicLong> a, Map.Entry<String, AtomicLong> b) {
            long d = b.getValue().get() - a.getValue().get();
            if (d < 0) return -1;
            if (d > 0) return 1;
            return a.getKey().compareTo(b.getKey());
          }
        });
    StringBuilder sb = new StringBuilder();
    sb.append("v=1\n");
    for (int i = 0; i < rows.size(); i++) {
      Map.Entry<String, AtomicLong> e = rows.get(i);
      long n = e.getValue().get();
      if (n <= 0) continue;
      sb.append(e.getKey().replace('\t', ' ').replace('\n', ' '));
      sb.append('\t');
      sb.append(n);
      sb.append('\n');
    }
    File tmp = new File(snapshot.getParentFile(), snapshot.getName() + ".tmp");
    FileOutputStream out = null;
    try {
      out = new FileOutputStream(tmp);
      out.write(sb.toString().getBytes(StandardCharsets.UTF_8));
      out.close();
      out = null;
      if (!tmp.renameTo(snapshot)) {
        // Don't truncate snapshot in place — a concurrent cat would flicker to empty.
        tmp.delete();
      }
    } catch (Exception ignored) {
      if (out != null) {
        try {
          out.close();
        } catch (Exception closeIgnored) {
        }
      }
    }
  }
}
