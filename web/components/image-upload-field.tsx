"use client";

import React, { useRef, useState } from "react";
import styles from "./image-upload-field.module.css";

interface ImageUploadFieldProps {
  label: string;
  value?: string | null;
  onChange: (url: string | null) => void;
  onUpload: (file: File) => Promise<string>;
  shape?: "square" | "circle";
  hint?: string;
  optional?: boolean;
}

export function ImageUploadField({
  label,
  value,
  onChange,
  onUpload,
  shape = "square",
  hint,
  optional = false,
}: ImageUploadFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleFile = async (file: File) => {
    setErrorMessage(null);
    setIsUploading(true);
    try {
      const deliveryUrl = await onUpload(file);
      onChange(deliveryUrl);
    } catch (err: unknown) {
      setErrorMessage((err as Error)?.message || "Failed to upload image.");
    } finally {
      setIsUploading(false);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
    }
  };

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      void handleFile(file);
    }
  };

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file && file.type.startsWith("image/")) {
      void handleFile(file);
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.labelRow}>
        <label className={styles.label}>{label}</label>
        {optional && <span className={styles.optional}>Optional</span>}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className={styles.hiddenInput}
        onChange={handleInputChange}
        disabled={isUploading}
      />

      {value ? (
        <div className={styles.previewCard}>
          <div
            className={`${styles.thumbnailWrapper} ${
              shape === "circle" ? styles.thumbnailCircle : ""
            }`}
          >
            <img src={value} alt={label} className={styles.thumbnail} />
          </div>

          <div className={styles.previewDetails}>
            {isUploading ? (
              <div className={styles.spinnerRow}>
                <div className={styles.spinner} />
                <span>Uploading...</span>
              </div>
            ) : (
              <div className={styles.previewActions}>
                <button
                  type="button"
                  className={styles.actionBtn}
                  onClick={() => inputRef.current?.click()}
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M12 20h9" />
                    <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                  </svg>
                  <span>Change</span>
                </button>

                <button
                  type="button"
                  className={`${styles.actionBtn} ${styles.removeBtn}`}
                  onClick={() => onChange(null)}
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                  <span>Remove</span>
                </button>
              </div>
            )}
            {hint && <span className={styles.dropzoneHint}>{hint}</span>}
          </div>
        </div>
      ) : (
        <div
          className={`${styles.dropzone} ${
            isDragging ? styles.dropzoneActive : ""
          }`}
          onClick={() => !isUploading && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          role="button"
          tabIndex={0}
        >
          {isUploading ? (
            <div className={styles.spinnerRow}>
              <div className={styles.spinner} />
              <span>Optimizing and uploading to cloud storage...</span>
            </div>
          ) : (
            <>
              <svg
                className={styles.dropzoneIcon}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                <circle cx="8.5" cy="8.5" r="1.5" />
                <polyline points="21 15 16 10 5 21" />
              </svg>
              <span className={styles.dropzoneText}>
                Choose photo or take picture
              </span>
              <span className={styles.dropzoneHint}>
                {hint || "Accepts any format (PNG, JPEG, WebP, HEIC, AVIF)"}
              </span>
            </>
          )}
        </div>
      )}

      {errorMessage && (
        <div className={styles.errorBanner}>{errorMessage}</div>
      )}
    </div>
  );
}
