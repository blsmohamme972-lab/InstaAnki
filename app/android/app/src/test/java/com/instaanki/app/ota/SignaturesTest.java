package com.instaanki.app.ota;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.ECGenParameterSpec;
import java.util.Base64;
import org.junit.Test;

public class SignaturesTest {

    private static KeyPair newKey() throws Exception {
        KeyPairGenerator g = KeyPairGenerator.getInstance("EC");
        g.initialize(new ECGenParameterSpec("secp256r1"));
        return g.generateKeyPair();
    }

    private static String pem(PublicKey key) {
        return "-----BEGIN PUBLIC KEY-----\n" + Base64.getMimeEncoder(64, "\n".getBytes()).encodeToString(key.getEncoded()) + "\n-----END PUBLIC KEY-----\n";
    }

    private static String sign(KeyPair kp, byte[] data) throws Exception {
        Signature s = Signature.getInstance("SHA256withECDSA");
        s.initSign(kp.getPrivate());
        s.update(data);
        return Base64.getEncoder().encodeToString(s.sign());
    }

    @Test
    public void acceptsOnlyTheRightKeyAndUntouchedData() throws Exception {
        KeyPair kp = newKey();
        byte[] data = "{\"bundleVersion\":\"0.2.0\"}".getBytes(StandardCharsets.UTF_8);
        String sig = sign(kp, data);
        PublicKey pub = Signatures.parsePublicKeyPem(pem(kp.getPublic()));

        assertTrue(Signatures.verify(pub, data, sig));
        assertTrue(Signatures.verify(pub, data, sig + "\n")); // trailing newline in the .sig file
        assertFalse(Signatures.verify(pub, "{\"bundleVersion\":\"9.9.9\"}".getBytes(StandardCharsets.UTF_8), sig));
        assertFalse(Signatures.verify(Signatures.parsePublicKeyPem(pem(newKey().getPublic())), data, sig));
        assertFalse(Signatures.verify(pub, data, "AAAA"));
        assertFalse(Signatures.verify(pub, data, "not base64 !!"));
    }

    private static byte[] resource(String name) throws IOException {
        try (InputStream in = SignaturesTest.class.getResourceAsStream("/ota/" + name)) {
            if (in == null) throw new IOException("missing test resource " + name);
            java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
            return out.toByteArray();
        }
    }

    /** Fixture produced by tools/ota/publish.mjs with a throwaway key: Node signer <-> Java verifier. */
    @Test
    public void verifiesManifestsSignedByThePublishTool() throws Exception {
        byte[] json = resource("latest.json");
        String sig = new String(resource("latest.json.sig"), StandardCharsets.UTF_8);
        PublicKey pub = Signatures.parsePublicKeyPem(new String(resource("test-public-key.pem"), StandardCharsets.UTF_8));
        assertTrue(Signatures.verify(pub, json, sig));
        OtaManifest m = OtaManifest.parse(json);
        assertEquals("0.2.0", m.bundleVersion);
        assertEquals(3, m.files.size());
        // any change to the signed bytes must break the signature
        byte[] tampered = json.clone();
        tampered[tampered.length - 3] ^= 1;
        assertFalse(Signatures.verify(pub, tampered, sig));
    }
}
