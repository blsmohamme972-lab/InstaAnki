package com.instaanki.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.Collections;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** One-time owner opt-in: GitHub-only Issues reporting, never an APK-embedded credential. */
final class GithubFeedback {
    interface Listener { void onStatus(String reportId, String state, String issueUrl); }
    private static final String REPO = "blsmohamme972-lab/InstaAnki";
    private static final String ALIAS = "instaanki-feedback-gh-aes-v1";
    private static final String SECRET = "token";
    private static final String QUEUED = "queued:";
    private static final String SENT = "sent:";
    private static final String LAST_ERROR = "last-error";
    private static final String VERIFIED = "verified";
    private static final class GitHubHttpFailure extends IOException {
        final int status;
        GitHubHttpFailure(int status) { super("GitHub HTTP failure"); this.status = status; }
    }
    /** Only predefined codes enter the web view: no credentials or response bodies. */
    private static String safeError(Exception error) {
        if (error instanceof GitHubHttpFailure) {
            int status = ((GitHubHttpFailure) error).status;
            if (status == 401) return "GitHub rejected the token (401). Replace it in Settings.";
            if (status == 403) return "GitHub denied access (403). Check Issues permission and token access.";
            if (status == 404) return "Repository unavailable to this token (404).";
            if (status == 422) return "GitHub rejected the report request (422).";
            if (status == 429) return "GitHub rate limit (429). Try again later.";
            if (status >= 500) return "GitHub service returned an error (" + status + ").";
            return "GitHub request failed (HTTP " + status + ").";
        }
        if (error instanceof java.net.UnknownHostException) return "Cannot reach api.github.com (DNS/network).";
        if (error instanceof java.net.SocketTimeoutException) return "Connection to GitHub timed out.";
        if (error instanceof javax.net.ssl.SSLException) return "Secure connection to GitHub failed.";
        if ("Stored token cannot be decrypted".equals(error.getMessage())) return "Saved GitHub token cannot be read. Reconnect in Settings.";
        if ("Invalid local report".equals(error.getMessage())) return "This saved report has invalid source metadata.";
        return "Network or GitHub request failed. Try Retry pending reports.";
    }
    private final SharedPreferences prefs;
    private final ExecutorService io;
    private final Listener listener;
    private final AtomicBoolean busy = new AtomicBoolean(false);

    GithubFeedback(Context context, ExecutorService executor, Listener callback) {
        prefs = context.getApplicationContext().getSharedPreferences("instaanki-github-reports", Context.MODE_PRIVATE);
        io = executor;
        listener = callback;
    }

    synchronized boolean pair(String token) {
        if (token == null || !token.matches("github_pat_[A-Za-z0-9_]{30,240}")) return false;
        try {
            KeyStore store = KeyStore.getInstance("AndroidKeyStore");
            store.load(null);
            if (!store.containsAlias(ALIAS)) {
                KeyGenerator g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
                g.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build());
                g.generateKey();
            }
            Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
            c.init(Cipher.ENCRYPT_MODE, (SecretKey) store.getKey(ALIAS,null));
            String value = Base64.encodeToString(c.getIV(),Base64.NO_WRAP)+":"+Base64.encodeToString(
                c.doFinal(token.getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP);
            boolean saved=prefs.edit().putString(SECRET,value).putBoolean(VERIFIED,false).remove(LAST_ERROR).commit();
            if(saved) flush();
            return saved;
        } catch(Exception e) { return false; }
    }

    synchronized boolean isPaired() { return prefs.contains(SECRET); }
    synchronized void unpair() { prefs.edit().remove(SECRET).putBoolean(VERIFIED,false).remove(LAST_ERROR).commit(); }
    synchronized String status() {
        int waiting=0, sent=0;
        for(String k:prefs.getAll().keySet()) {
            if(k.startsWith(QUEUED)) waiting++;
            if(k.startsWith(SENT)) sent++;
        }
        try { return new JSONObject().put("connected",isPaired())
            .put("verified",prefs.getBoolean(VERIFIED,false))
            .put("lastError",prefs.getString(LAST_ERROR,""))
            .put("queued",waiting).put("sent",sent).toString(); }
        catch (Exception ignored) { return "{\"connected\":false,\"queued\":0,\"sent\":0}"; }
    }

    /** Persist before network access; a failed upload retains the report for a later retry. */
    synchronized boolean queue(String raw) {
        if(!isPaired() || raw == null || raw.getBytes(StandardCharsets.UTF_8).length > 40000) return false;
        try {
            JSONObject report=validate(new JSONObject(raw));
            String id=report.getString("reportId");
            if(prefs.contains(SENT+id)) return true;
            int pending=0;
            for(String key:prefs.getAll().keySet()) if(key.startsWith(QUEUED)) pending++;
            if(pending>=100 && !prefs.contains(QUEUED+id)) return false;
            if(!prefs.edit().putString(QUEUED+id,report.toString()).commit()) return false;
            flush();
            return true;
        } catch(Exception e) { return false; }
    }

    void flush() {
        if(!isPaired() || !busy.compareAndSet(false,true)) return;
        io.execute(() -> {
            try {
                ArrayList<String> entries=new ArrayList<>();
                for(String k:prefs.getAll().keySet()) if(k.startsWith(QUEUED)) entries.add(k);
                Collections.sort(entries);
                for(String key:entries) {
                    String json=prefs.getString(key,null);
                    if(json==null) continue;
                    String reportId=key.substring(QUEUED.length());
                    try {
                        JSONObject report;
                        try { report=validate(new JSONObject(json)); }
                        catch(Exception badReport) { throw new IOException("Invalid local report"); }
                        if(!reportId.equals(report.getString("reportId"))) throw new IOException("Wrong report ID");
                        String token=decrypt();
                        if(token==null) throw new IOException("Stored token cannot be decrypted");
                        String issue=submit(token,report);
                        if(!issue.startsWith("https://github.com/"+REPO+"/issues/"))
                            throw new IOException("Wrong GitHub response");
                        if(prefs.edit().putString(SENT+reportId,issue).remove(key)
                                .putBoolean(VERIFIED,true).remove(LAST_ERROR).commit())
                            listener.onStatus(reportId,"sent",issue);
                    } catch(Exception error) {
                        prefs.edit().putString(LAST_ERROR,safeError(error)).commit();
                        listener.onStatus(reportId,"queued","");
                        return;
                    }
                }
            } finally { busy.set(false); }
        });
    }

    private synchronized String decrypt() {
        try {
            String[] p=prefs.getString(SECRET,"").split(":",-1);
            if(p.length!=2) return null;
            KeyStore store=KeyStore.getInstance("AndroidKeyStore");
            store.load(null);
            SecretKey key=(SecretKey)store.getKey(ALIAS,null);
            if(key==null) return null;
            Cipher c=Cipher.getInstance("AES/GCM/NoPadding");
            c.init(Cipher.DECRYPT_MODE,key,new GCMParameterSpec(128,Base64.decode(p[0],Base64.NO_WRAP)));
            return new String(c.doFinal(Base64.decode(p[1],Base64.NO_WRAP)),StandardCharsets.UTF_8);
        } catch(Exception error) { return null; }
    }

    private static boolean safeId(String s) {
        return s!=null && s.matches("[A-Za-z0-9][A-Za-z0-9._-]{0,119}") &&
            !s.equals("constructor") && !s.equals("__proto__") && !s.equals("prototype");
    }
    private static JSONObject validate(JSONObject input) throws Exception {
        String id=input.getString("id"),lesson=input.getString("lessonId"),reason=input.getString("reason");
        if(!safeId(id)||!id.startsWith("feedback-")||!safeId(lesson)) throw new IOException("Invalid ID");
        if(!java.util.Arrays.asList("bad_images","bad_sound","bad_timing","bad_mcq","wrong_source","other").contains(reason))
            throw new IOException("Invalid category");
        String comment=input.optString("comment","");
        if(comment.length()>4000) throw new IOException("Comment too long");
        String timestamp=input.getString("createdAt");
        java.time.Instant.parse(timestamp);
        JSONObject src=input.getJSONObject("source");
        String book=src.getString("bookId");
        int question=src.getInt("questionNumber");
        if(!safeId(book)||question<1||question>1000000) throw new IOException("Invalid source");
        int version=input.optInt("lessonVersion",1);
        if(version<1||version>1000000) throw new IOException("Invalid version");
        JSONObject hashes=new JSONObject();
        JSONObject given=input.optJSONObject("assetHashes");
        if(given!=null) {
            if(given.length()>200) throw new IOException("Too many references");
            java.util.Iterator<String> it=given.keys();
            while(it.hasNext()) {
                String path=it.next(), hash=given.getString(path);
                if(path.length()>320||!path.matches("[A-Za-z0-9][A-Za-z0-9._/-]*")
                    || path.contains("../")||path.endsWith("/..")||!hash.matches("[0-9a-fA-F]{64}"))
                    throw new IOException("Invalid asset hash");
                hashes.put(path,hash.toLowerCase(java.util.Locale.ROOT));
            }
        }
        return new JSONObject().put("reportId",id).put("lessonId",lesson).put("reason",reason)
            .put("lessonVersion",version).put("createdAt",timestamp).put("comment",comment)
            .put("source",new JSONObject().put("bookId",book).put("questionNumber",question))
            .put("assetHashes",hashes);
    }

    private static String submit(String token, JSONObject report) throws Exception {
        String marker="instaanki-report-id:"+report.getString("reportId");
        // GitHub Issues:read/write grants the ordinary repository Issues listing.
        // Avoid the separate Search API permissions and search-specific throttling.
        JSONObject result=call(token,"GET","/repos/"+REPO+
            "/issues?state=all&sort=created&direction=desc&per_page=100",null);
        JSONArray found=result.optJSONArray("items");
        if(found!=null) for(int i=0;i<found.length();i++) {
            JSONObject issue=found.optJSONObject(i);
            if(issue!=null && issue.optString("body","").contains("<!-- "+marker+" -->")) {
                String url=issue.optString("html_url","");
                if(url.matches("https://github[.]com/blsmohamme972-lab/InstaAnki/issues/[0-9]+")) return url;
            }
        }
        JSONObject created=call(token,"POST","/repos/"+REPO+"/issues",
            new JSONObject().put("title","[InstaAnki] "+report.getString("lessonId")+" / "+report.getString("reason"))
                .put("body",body(report,marker)));
        String url=created.getString("html_url");
        if(!url.matches("https://github[.]com/blsmohamme972-lab/InstaAnki/issues/[0-9]+"))
            throw new IOException("Invalid issue confirmation");
        return url;
    }

    private static String body(JSONObject r,String marker) throws Exception {
        String comment=r.getString("comment").replace("<","&lt;").replace(">","&gt;").replace("@","&#64;");
        return "<!-- "+marker+" -->\n## InstaAnki one-tap lesson report\n"
            + "\nLesson ID: "+r.getString("lessonId")
            + "\nRevision: "+r.getInt("lessonVersion")
            + "\nReason: "+r.getString("reason")
            + "\nBook: "+r.getJSONObject("source").getString("bookId")
            + "\nQuestion: "+r.getJSONObject("source").getInt("questionNumber")
            + "\nDate: "+r.getString("createdAt")
            + "\n\nComment:\n"+(comment.isEmpty()?"(none)":comment)
            + "\n\nMedia SHA-256 fingerprints:\n"+r.getJSONObject("assetHashes").toString(2)
            + "\n\nReview medical accuracy and image provenance before any replacement. Do not auto-publish.\n";
    }

    private static JSONObject call(String token,String method,String path,JSONObject payload) throws Exception {
        HttpURLConnection conn=(HttpURLConnection)new URL("https://api.github.com"+path).openConnection();
        conn.setInstanceFollowRedirects(false);
        conn.setRequestMethod(method);
        conn.setConnectTimeout(12000);
        conn.setReadTimeout(15000);
        conn.setRequestProperty("Authorization","Bearer "+token);
        conn.setRequestProperty("Accept","application/vnd.github+json");
        conn.setRequestProperty("X-GitHub-Api-Version","2022-11-28");
        conn.setRequestProperty("User-Agent","InstaAnki-Feedback");
        try {
            if(payload!=null) {
                byte[] bytes=payload.toString().getBytes(StandardCharsets.UTF_8);
                conn.setDoOutput(true);
                conn.setRequestProperty("Content-Type","application/json; charset=utf-8");
                conn.setFixedLengthStreamingMode(bytes.length);
                try(OutputStream out=conn.getOutputStream()) { out.write(bytes); }
            }
            int responseCode=conn.getResponseCode();
            if(responseCode!=(payload==null?200:201)) throw new GitHubHttpFailure(responseCode);
            try(InputStream in=conn.getInputStream();ByteArrayOutputStream buf=new ByteArrayOutputStream()) {
                byte[] chunk=new byte[4096];int count;
                while((count=in.read(chunk))!=-1) {
                    if(buf.size()+count>256000)throw new IOException("Response too large");
                    buf.write(chunk,0,count);
                }
                String response=new String(buf.toByteArray(),StandardCharsets.UTF_8);
                if(payload==null && method.equals("GET") && path.startsWith("/repos/"+REPO+"/issues?"))
                    return new JSONObject().put("items",new JSONArray(response));
                return new JSONObject(response);
            }
        } finally { conn.disconnect(); }
    }
}
