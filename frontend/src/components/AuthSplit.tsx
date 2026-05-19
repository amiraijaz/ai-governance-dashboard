import { ReactNode } from "react";

/**
 * Two-column auth layout:
 *   - Left (60%): full-bleed background video; hidden below md.
 *   - Right (40%): centered form panel, white background.
 * No page scroll; both columns fill the viewport.
 */
export default function AuthSplit({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-white">
      {/* Left visual panel */}
      <div className="relative hidden md:block md:w-3/5">
        <video
          src="/brand-video.mp4"
          autoPlay
          muted
          loop
          playsInline
          poster=""
          className="absolute inset-0 h-full w-full object-cover"
          aria-hidden
        />
        {/* Subtle gradient so the brand mark + helper read on any video */}
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(180deg, rgba(15,23,42,0.15) 0%, rgba(15,23,42,0.35) 100%)",
          }}
        />

        {/* Top-left brand mark */}
        <div className="absolute left-8 top-8 flex items-center gap-2 text-white">
          <span
            className="flex h-8 w-8 items-center justify-center rounded-full"
            style={{ background: "var(--vigil-green)" }}
          >
            <svg
              viewBox="0 0 24 24"
              width="16"
              height="16"
              fill="none"
              stroke="white"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 2 4 5v6c0 5 3.5 9 8 11 4.5-2 8-6 8-11V5l-8-3Z" />
              <circle cx="12" cy="11" r="2.2" />
            </svg>
          </span>
          <span className="text-base font-semibold tracking-tight">Vigil</span>
        </div>

      </div>

      {/* Right form panel */}
      <div className="flex w-full items-center justify-center md:w-2/5">
        <div className="w-full max-w-sm px-6 py-12 md:px-12">{children}</div>
      </div>
    </div>
  );
}