import { ReactNode } from "react";

const BRAND_BG = "#04342C";

export default function AuthSplit({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen w-full">
      <BrandPanel />
      <section className="flex w-full items-center justify-center bg-white px-6 py-10 md:w-2/5 md:px-12 md:py-12">
        <div className="w-full max-w-sm">{children}</div>
      </section>
    </div>
  );
}

function BrandPanel() {
  return (
    <aside
      className="relative hidden overflow-hidden md:flex md:w-3/5"
      style={{ background: BRAND_BG }}
    >
      <video
        src="/login_video.mp4"
        autoPlay
        loop
        muted
        playsInline
        className="absolute inset-0 h-full w-full object-cover"
      />

      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent" />

      <div className="absolute bottom-10 left-10 z-10">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{ background: "#2bb482" }}
          />
          <span
            className="font-semibold tracking-tight text-white"
            style={{ fontSize: 20 }}
          >
            Vigil
          </span>
        </div>
        <p
          className="mt-2 max-w-xs"
          style={{ fontSize: 13, color: "rgba(255,255,255,0.6)" }}
        >
          Know exactly what your AI is doing
        </p>
      </div>
    </aside>
  );
}
