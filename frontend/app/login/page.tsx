"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { resetIdentity } from "@/components/AppShell";
import { Alert, Button, Field, inputClass } from "@/components/ui";
import { api, errorMessage, setCsrfToken, setIdentityReady } from "@/lib/api";
import type { Me } from "@/lib/types";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const me = await api<Me>("/api/auth/login", { body: { username, password } });
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
    <main className="flex flex-1 items-center justify-center px-4 py-12">
      <form onSubmit={submit} className="w-full max-w-sm space-y-5 rounded-2xl border border-line bg-surface p-6 sm:p-8">
        <div>
          <div aria-hidden className="mb-4 grid size-10 place-items-center rounded-xl bg-accent text-accent-fg">▼</div>
          <h1 className="text-xl font-semibold">Sign in</h1>
          <p className="mt-1 text-sm text-muted">Private video dashboard. Administrators only.</p>
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
        <Button type="submit" loading={loading} className="w-full">Sign in</Button>
      </form>
    </main>
  );
}
