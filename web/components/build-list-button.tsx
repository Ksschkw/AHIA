"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ItemBoxIcon } from "@/components/icons";

export function BuildListButton({
  href,
  className,
  children,
}: {
  href: string;
  className?: string;
  children?: React.ReactNode;
}) {
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    if (loading) return;
    setLoading(true);
    router.push(href);
  };

  return (
    <a
      href={href}
      onClick={handleClick}
      className={className}
      style={{
        opacity: loading ? 0.8 : 1,
        pointerEvents: loading ? "none" : "auto",
        transition: "opacity 0.15s ease",
      }}
    >
      {loading ? (
        <>
          <span
            style={{
              display: "inline-block",
              width: 14,
              height: 14,
              border: "2px solid currentColor",
              borderTopColor: "transparent",
              borderRadius: "50%",
              animation: "spin 0.6s linear infinite",
            }}
          />
          <span>Opening List...</span>
        </>
      ) : (
        children || (
          <>
            <ItemBoxIcon size={16} />
            <span>Build your list</span>
          </>
        )
      )}
    </a>
  );
}
