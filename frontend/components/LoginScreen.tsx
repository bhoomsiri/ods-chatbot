"use client";

import type { Identity } from "@/lib/identity";

function GoogleIcon() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

/**
 * Login landing shown first on every fresh app load (the `entered` gate in
 * page.tsx is in-memory, so closing/reopening or refreshing shows it again).
 * The real Google authentication is enforced upstream by Cloudflare Access;
 * this is the in-app entry step. `identity` (when known) confirms who Cloudflare
 * already signed in; `onContinue` proceeds into the chat.
 */
export default function LoginScreen({
  identity,
  onContinue,
}: {
  identity: Identity | null;
  onContinue: () => void;
}) {
  return (
    <main className="flex h-screen w-full items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 shadow-lg">
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-600 text-sm font-bold text-white">
            ODS
          </div>
          <h1 className="text-2xl font-semibold text-slate-900">เข้าสู่ระบบ</h1>
          <p className="mt-2 text-sm text-slate-500">
            ผู้ช่วยให้ข้อมูลการผ่าตัดแบบวันเดียวกลับ (ODS)
            <br />
            โรงพยาบาลโพธาราม
          </p>
        </div>

        <button
          type="button"
          onClick={onContinue}
          className="flex w-full items-center justify-center gap-3 rounded-full border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-800 transition hover:bg-slate-50"
        >
          <GoogleIcon />
          เข้าสู่ระบบด้วย Google
        </button>

        <p className="mt-4 text-center text-xs text-slate-400">
          {identity ? (
            <>
              เข้าสู่ระบบในชื่อ{" "}
              <span className="font-medium text-slate-500">{identity.email}</span>
            </>
          ) : (
            "เข้าสู่ระบบอย่างปลอดภัยผ่าน Cloudflare Access"
          )}
        </p>
      </div>
    </main>
  );
}
