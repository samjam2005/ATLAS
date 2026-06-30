import { useCallback } from "react";
import { apiPost } from "@/lib/api";
import { useAppStore } from "@/store/useAppStore";
import type { ZODigest } from "@/types";

export function useZODigest() {
  const setZODigest = useAppStore((s) => s.setZODigest);
  const setZODigestLoading = useAppStore((s) => s.setZODigestLoading);
  const digest = useAppStore((s) => s.zoDigest);
  const loading = useAppStore((s) => s.zoDigestLoading);

  const parseEmails = useCallback(
    async (emailText: string) => {
      if (!emailText.trim()) return;
      setZODigestLoading(true);
      setZODigest(null);
      try {
        const result = await apiPost<ZODigest>("/zo/parse", { email_text: emailText });
        setZODigest(result);
      } catch (err) {
        console.error("ZO parse error:", err);
        throw err;
      } finally {
        setZODigestLoading(false);
      }
    },
    [setZODigest, setZODigestLoading],
  );

  return { parseEmails, digest, loading };
}
