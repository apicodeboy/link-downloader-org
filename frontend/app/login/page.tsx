"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { resetIdentity } from "@/components/AppShell";
import { Frame, Wordmark } from "@/components/Frame";
import { SITE_NAME } from "@/lib/site";
import { Alert, Button, Field, inputClass } from "@/components/ui";
import { api, errorMessage, setCsrfToken, setIdentityReady } from "@/lib/api";
import type { Me } from "@/lib/types";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const me = await api<Me>("/api/auth/login", { body: { username, password, remember } });
      setCsrfToken(me.csrf_token);
      setIdentityReady();
      resetIdentity();
      const next = new URLSearchParams(window.location.search).get("next") || "/";
      router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (err) {
      setError(errorMessage(err));
      setLoading(false);
    }
  };

  return (
    <Frame>
    <main className="flex flex-1 items-center justify-center px-4 py-12">
      <form onSubmit={submit} className="w-full max-w-sm space-y-5 rounded-3xl border border-cream/10 bg-surface/80 p-6 backdrop-blur sm:p-8">
        <div>
          <Wordmark name={SITE_NAME} />
          <h1 className="font-display mt-6 text-4xl text-cream">Sign in</h1>
          <p className="mt-1 text-sm text-muted">Site owner sign-in. Visitors don&apos;t need an account.</p>
        </div>
        {error && <Alert>{error}</Alert>}
        <Field label="Username">
          <input className={inputClass} autoComplete="username" autoCapitalize="none" required value={username}
                 onChange={(e) => setUsername(e.target.value)} />
        </Field>
        <Field label="Password">
          <input className={inputClass} type="password" autoComplete="current-password" required value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <label className="flex items-center gap-2 text-sm text-muted">
          <input type="checkbox" className="size-4 accent-[var(--color-accent)]" checked={remember}
                 onChange={(e) => setRemember(e.target.checked)} />
          Keep me signed in on this device
        </label>
        <Button type="submit" loading={loading} className="w-full">Sign in</Button>
      </form>
    </main>
    </Frame>
  );
}
