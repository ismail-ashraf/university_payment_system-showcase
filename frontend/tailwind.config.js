/** @type {import("tailwindcss").Config} */
module.exports = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        ink: "#0f172a",
        mist: "#f1f5f9",
        ocean: "#1e3a8a",
        sea: "#0ea5e9"
      }
    }
  },
  plugins: []
};
