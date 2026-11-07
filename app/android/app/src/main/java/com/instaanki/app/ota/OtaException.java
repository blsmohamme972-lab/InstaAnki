package com.instaanki.app.ota;

/** A problem with an update (bad manifest, bad signature, hash mismatch...). */
public class OtaException extends Exception {

    public OtaException(String message) {
        super(message);
    }

    public OtaException(String message, Throwable cause) {
        super(message, cause);
    }
}
