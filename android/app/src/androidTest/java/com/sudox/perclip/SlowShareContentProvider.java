package com.sudox.perclip;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.FileNotFoundException;
import java.io.IOException;

/** Test-only provider that keeps URI copying active long enough to recreate the transient Activity. */
public final class SlowShareContentProvider extends ContentProvider {
    public static final Uri URI =
            Uri.parse("content://com.sudox.perclip.dev.test.slowshare/recreate");

    private static final String DISPLAY_NAME = "stage23-8d3a-recreate.bin";
    private static final String MIME_TYPE = "application/octet-stream";
    private static final long COPY_DELAY_MS = 1_500L;
    private static final int CHUNK_SIZE = 16 * 1024;
    private static final int PAYLOAD_SIZE = 1024 * 1024;

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public String getType(Uri uri) {
        return MIME_TYPE;
    }

    @Override
    public Cursor query(
            Uri uri,
            String[] projection,
            String selection,
            String[] selectionArgs,
            String sortOrder
    ) {
        MatrixCursor cursor = new MatrixCursor(
                new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE}
        );
        cursor.addRow(new Object[]{DISPLAY_NAME, PAYLOAD_SIZE});
        return cursor;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        final ParcelFileDescriptor[] pipe;
        try {
            pipe = ParcelFileDescriptor.createPipe();
        } catch (IOException exception) {
            throw new FileNotFoundException(exception.getMessage());
        }
        new Thread(() -> {
            try (ParcelFileDescriptor.AutoCloseOutputStream output =
                         new ParcelFileDescriptor.AutoCloseOutputStream(pipe[1])) {
                Thread.sleep(COPY_DELAY_MS);
                byte[] chunk = new byte[CHUNK_SIZE];
                for (int index = 0; index < chunk.length; index++) {
                    chunk[index] = (byte) (index % 251);
                }
                for (int written = 0; written < PAYLOAD_SIZE; written += CHUNK_SIZE) {
                    output.write(chunk);
                }
            } catch (IOException ignored) {
                // The first reader is expected to close its pipe when Activity recreation cancels it.
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            }
        }, "slow-share-provider").start();
        return pipe[0];
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        return 0;
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        return 0;
    }
}
