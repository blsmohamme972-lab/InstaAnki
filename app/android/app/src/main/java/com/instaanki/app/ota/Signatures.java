package com.instaanki.app.ota;

import java.security.GeneralSecurityException;
import java.security.KeyFactory;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.X509EncodedKeySpec;

/**
 * Update manifests are signed with ECDSA P-256 / SHA-256 (natively supported on every Android
 * version, no extra library). The .sig file holds the Base64 DER signature of the exact bytes of
 * latest.json; the public key is embedded in the APK.
 */
public final class Signatures {

    private Signatures() {}

    public static PublicKey parsePublicKeyPem(String pem) throws OtaException {
        String body = pem.replace("-----BEGIN PUBLIC KEY-----", "").replace("-----END PUBLIC KEY-----", "");
        try {
            return KeyFactory.getInstance("EC").generatePublic(new X509EncodedKeySpec(Hashing.base64Decode(body)));
        } catch (GeneralSecurityException e) {
            throw new OtaException("invalid public key", e);
        }
    }

    public static boolean verify(PublicKey key, byte[] data, String signatureBase64) {
        try {
            Signature sig = Signature.getInstance("SHA256withECDSA");
            sig.initVerify(key);
            sig.update(data);
            return sig.verify(Hashing.base64Decode(signatureBase64));
        } catch (GeneralSecurityException | OtaException e) {
            return false;
        }
    }
}
