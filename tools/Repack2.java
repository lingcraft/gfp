import java.io.*;
import java.util.*;
import java.util.zip.*;

/** 通用 APK 条目替换重打包。
 *  用法: Repack2 <src.apk> <out.apk> [entry_name=local_file ...]
 *  自动剔除 META-INF 旧签名；STORED 条目保留 STORED 并预设 size/crc。
 */
public class Repack2 {
    public static void main(String[] args) throws Exception {
        if (args.length < 3) {
            System.err.println("usage: Repack2 <src.apk> <out.apk> [entry=file ...]");
            System.exit(2);
        }
        String srcApk = args[0];
        String outApk = args[1];

        // 解析替换表
        Map<String, File> replace = new LinkedHashMap<>();
        for (int i = 2; i < args.length; i++) {
            int eq = args[i].indexOf('=');
            replace.put(args[i].substring(0, eq), new File(args[i].substring(eq + 1)));
            System.out.println("替换: " + args[i].substring(0, eq) + " <- " + args[i].substring(eq + 1));
        }

        ZipFile zin = new ZipFile(srcApk);
        ZipOutputStream zout = new ZipOutputStream(new FileOutputStream(outApk));
        zout.setLevel(9);

        Enumeration<? extends ZipEntry> en = zin.entries();
        int skipped = 0, written = 0, replaced = 0;
        while (en.hasMoreElements()) {
            ZipEntry e = en.nextElement();
            String name = e.getName();
            if (name.startsWith("META-INF/") &&
                (name.endsWith(".MF") || name.endsWith(".SF") || name.endsWith(".RSA") ||
                 name.endsWith(".DSA") || name.endsWith(".EC"))) {
                skipped++;
                continue;
            }

            InputStream is;
            ZipEntry ne = new ZipEntry(name);
            long size, crc;

            if (replace.containsKey(name)) {
                File f = replace.get(name);
                // 预计算替换内容的 CRC（STORED 需要）
                size = f.length();
                CRC32 c = new CRC32();
                InputStream cs = new FileInputStream(f);
                byte[] cbuf = new byte[1 << 20];
                int cn;
                while ((cn = cs.read(cbuf)) > 0) c.update(cbuf, 0, cn);
                cs.close();
                crc = c.getValue();

                is = new FileInputStream(f);
                // ★ 大文件（如 sparsepck）必须保持 STORED 未压缩——Godot 依赖 mmap 直读
                if (e.getMethod() == ZipEntry.STORED || size > (100L << 20)) {
                    ne.setMethod(ZipEntry.STORED);
                    ne.setSize(size);
                    ne.setCompressedSize(size);
                    ne.setCrc(crc);
                    zout.putNextEntry(ne);
                    copyStream(is, zout);
                } else {
                    ne.setMethod(ZipEntry.DEFLATED);
                    zout.putNextEntry(ne);
                    copyStream(is, zout);
                }
                replaced++;
            } else if (e.getMethod() == ZipEntry.STORED) {
                is = zin.getInputStream(e);
                ne.setMethod(ZipEntry.STORED);
                ne.setSize(e.getSize());
                ne.setCompressedSize(e.getCompressedSize());
                ne.setCrc(e.getCrc());
                zout.putNextEntry(ne);
                copyStream(is, zout);
            } else {
                is = zin.getInputStream(e);
                ne.setMethod(ZipEntry.DEFLATED);
                zout.putNextEntry(ne);
                copyStream(is, zout);
            }
            zout.closeEntry();
            if (is != null) is.close();
            written++;
        }
        zin.close();
        zout.close();
        System.out.println("done. written=" + written + " replaced=" + replaced + " skipped_signatures=" + skipped);
        System.out.println("output=" + outApk);
    }

    static void copyStream(InputStream in, OutputStream out) throws Exception {
        byte[] buf = new byte[8 * 1024 * 1024];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
    }
}
