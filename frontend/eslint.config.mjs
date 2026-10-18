import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

const config = [
  ...coreWebVitals,
  ...typescript,
  {
    rules: {
      // Pages read localStorage / sessionStorage / the clock after hydration (client-only data), which needs
      // setState in an effect. Kept as a warning so new code still gets the hint.
      "react-hooks/set-state-in-effect": "warn",
      // Retailer photos are arbitrary https links; next/image would need every host allow-listed.
      "@next/next/no-img-element": "off",
    },
  },
  { ignores: [".next/**", "node_modules/**", "public/sw.js", "next-env.d.ts"] },
];

export default config;
