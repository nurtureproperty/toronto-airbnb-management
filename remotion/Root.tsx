import { Composition } from "remotion";
import { SocialPromo } from "./SocialPromo";

export const RemotionRoot = () => {
  return (
    <Composition
      id="SocialPromo"
      component={SocialPromo}
      durationInFrames={300}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{
        title: "Earn 30-100% More",
        subtitle: "by switching to Airbnb",
        stats: [
          { value: "4.9★", label: "Average Rating" },
          { value: "9 min", label: "Response Time" },
          { value: "10-15%", label: "Management Fee" },
        ],
        cta: "Get Your Free Estimate",
        phone: "(647) 957-8956",
      }}
    />
  );
};
