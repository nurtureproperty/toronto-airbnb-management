import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
  Sequence,
} from "remotion";

type Stat = {
  value: string;
  label: string;
};

export type SocialPromoProps = {
  title: string;
  subtitle: string;
  stats: Stat[];
  cta: string;
  phone: string;
};

// Brand colors from CLAUDE.md
const colors = {
  primary: "#759b8f",
  primaryDark: "#5a7d73",
  accent: "#d4a373",
  background: "#FFFDF9",
  backgroundAlt: "#F8F6F1",
  text: "#2d3436",
};

export const SocialPromo: React.FC<SocialPromoProps> = ({
  title,
  subtitle,
  stats,
  cta,
  phone,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Logo entrance animation
  const logoScale = spring({
    frame,
    fps,
    config: { damping: 12 },
  });

  // Title entrance (starts at 0.5s)
  const titleProgress = spring({
    frame: frame - 0.5 * fps,
    fps,
    config: { damping: 200 },
  });

  const titleY = interpolate(titleProgress, [0, 1], [100, 0]);
  const titleOpacity = interpolate(titleProgress, [0, 1], [0, 1]);

  // Subtitle entrance (starts at 1s)
  const subtitleProgress = spring({
    frame: frame - 1 * fps,
    fps,
    config: { damping: 200 },
  });

  const subtitleOpacity = interpolate(subtitleProgress, [0, 1], [0, 1]);

  // Stats entrance (staggered, starts at 2s)
  const getStatAnimation = (index: number) => {
    const delay = 2 * fps + index * 0.3 * fps;
    const progress = spring({
      frame: frame - delay,
      fps,
      config: { damping: 15 },
    });
    return {
      scale: interpolate(progress, [0, 1], [0.5, 1]),
      opacity: interpolate(progress, [0, 1], [0, 1]),
    };
  };

  // CTA entrance (starts at 4s)
  const ctaProgress = spring({
    frame: frame - 4 * fps,
    fps,
    config: { damping: 12 },
  });

  const ctaScale = interpolate(ctaProgress, [0, 1], [0.8, 1]);
  const ctaOpacity = interpolate(ctaProgress, [0, 1], [0, 1]);

  // Phone pulse animation (starts at 5s)
  const phonePulse =
    frame > 5 * fps
      ? 1 + 0.05 * Math.sin((frame - 5 * fps) * 0.15)
      : 0;
  const phoneOpacity = interpolate(
    frame,
    [5 * fps, 5.5 * fps],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill
      style={{
        backgroundColor: colors.background,
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      {/* Background accent shape */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: "45%",
          backgroundColor: colors.primary,
          borderBottomLeftRadius: 80,
          borderBottomRightRadius: 80,
        }}
      />

      {/* Logo/Brand */}
      <div
        style={{
          position: "absolute",
          top: 120,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          transform: `scale(${logoScale})`,
        }}
      >
        <div
          style={{
            fontSize: 72,
            fontWeight: 700,
            color: colors.background,
            letterSpacing: "-2px",
          }}
        >
          Nurture
        </div>
      </div>

      {/* Main Title */}
      <div
        style={{
          position: "absolute",
          top: 350,
          left: 60,
          right: 60,
          textAlign: "center",
          transform: `translateY(${titleY}px)`,
          opacity: titleOpacity,
        }}
      >
        <div
          style={{
            fontSize: 96,
            fontWeight: 800,
            color: colors.background,
            lineHeight: 1.1,
          }}
        >
          {title}
        </div>
        <div
          style={{
            fontSize: 48,
            fontWeight: 500,
            color: colors.backgroundAlt,
            marginTop: 20,
            opacity: subtitleOpacity,
          }}
        >
          {subtitle}
        </div>
      </div>

      {/* Stats Grid */}
      <div
        style={{
          position: "absolute",
          top: 850,
          left: 60,
          right: 60,
          display: "flex",
          flexDirection: "column",
          gap: 40,
        }}
      >
        {stats.map((stat, index) => {
          const anim = getStatAnimation(index);
          return (
            <div
              key={index}
              style={{
                backgroundColor: colors.backgroundAlt,
                borderRadius: 30,
                padding: "40px 50px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                transform: `scale(${anim.scale})`,
                opacity: anim.opacity,
                boxShadow: "0 10px 40px rgba(0,0,0,0.08)",
              }}
            >
              <span
                style={{
                  fontSize: 56,
                  fontWeight: 700,
                  color: colors.primary,
                }}
              >
                {stat.value}
              </span>
              <span
                style={{
                  fontSize: 36,
                  fontWeight: 500,
                  color: colors.text,
                }}
              >
                {stat.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* CTA Button */}
      <div
        style={{
          position: "absolute",
          bottom: 280,
          left: 60,
          right: 60,
          display: "flex",
          justifyContent: "center",
          transform: `scale(${ctaScale})`,
          opacity: ctaOpacity,
        }}
      >
        <div
          style={{
            backgroundColor: colors.accent,
            color: colors.background,
            fontSize: 42,
            fontWeight: 700,
            padding: "36px 60px",
            borderRadius: 60,
            boxShadow: "0 15px 50px rgba(212, 163, 115, 0.4)",
          }}
        >
          {cta}
        </div>
      </div>

      {/* Phone Number */}
      <div
        style={{
          position: "absolute",
          bottom: 150,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          opacity: phoneOpacity,
          transform: `scale(${phonePulse || 1})`,
        }}
      >
        <div
          style={{
            fontSize: 48,
            fontWeight: 600,
            color: colors.primaryDark,
          }}
        >
          {phone}
        </div>
      </div>
    </AbsoluteFill>
  );
};
