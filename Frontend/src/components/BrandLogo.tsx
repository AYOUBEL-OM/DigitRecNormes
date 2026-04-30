import { cn } from "@/lib/utils";
import logoBlue from "@/assets/brand/digitrec-blue.png";
import logoWhite from "@/assets/brand/digitrec-white.png";
import { Briefcase, Sparkles } from "lucide-react";

export type BrandLogoProps = {
  variant?: "light" | "dark";
  size?: "xs" | "sm" | "md" | "lg" | "xl" | "hero";
  className?: string;
  showText?: boolean;
  /** Compense un padding transparent interne du PNG (grossit visuellement). */
  compact?: boolean;
  /** Mode sidebar repliée : affiche un mark compact au lieu du logo horizontal. */
  collapsed?: boolean;
};

const SIZE_CLASS: Record<NonNullable<BrandLogoProps["size"]>, string> = {
  xs: "h-6",
  sm: "h-8",
  md: "h-12",
  // Sidebar ouverte : ~56px max
  lg: "h-14",
  xl: "h-24",
  hero: "h-32",
};

export function BrandLogo({
  variant = "light",
  size = "md",
  className,
  showText = false,
  compact = false,
  collapsed = false,
}: BrandLogoProps) {
  const logoSrc = variant === "dark" ? logoWhite : logoBlue;

  if (collapsed) {
    const boxSize = "h-10 w-10"; // ~40px (dans la cible 36–42)
    const iconSize = "h-5 w-5";
    return (
      <div className={cn("flex items-center justify-center", className)} aria-label="DigitRec">
        <div
          className={cn(
            "relative flex shrink-0 items-center justify-center rounded-xl shadow-md ring-1 ring-white/15",
            "bg-gradient-to-br from-indigo-700 via-blue-700 to-sky-500 text-white",
            boxSize,
          )}
          aria-hidden
        >
          <Briefcase className={cn(iconSize, "opacity-95")} strokeWidth={2.25} />
          <Sparkles
            className="absolute -right-0.5 -top-0.5 h-3 w-3 text-sky-200 drop-shadow"
            strokeWidth={2}
            aria-hidden
          />
        </div>
      </div>
    );
  }

  return (
    <div className={cn("flex min-w-0 items-center gap-2", className)}>
      <div className="overflow-visible">
      <img
        src={logoSrc}
        alt="DigitRec"
        className={cn(
          SIZE_CLASS[size],
          "w-auto object-contain shrink-0",
          compact && "scale-[1.45] origin-center",
        )}
        draggable={false}
      />
      </div>
      {showText ? (
        <span
          className={cn(
            "truncate font-semibold tracking-tight",
            variant === "dark" ? "text-white" : "text-slate-900",
          )}
        >
          DigitRec
        </span>
      ) : null}
    </div>
  );
}
