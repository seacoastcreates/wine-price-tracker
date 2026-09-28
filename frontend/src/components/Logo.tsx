/** The Cellar Index mark: a wine glass on a burgundy tile (matches the favicon). */
export default function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="14" fill="#7a1f35" />
      <path d="M18 9h28c0 15.5-5.3 26-14 26S18 24.5 18 9z" fill="none" stroke="#f6e7c8" strokeWidth="4" strokeLinejoin="round" />
      <path d="M20.6 19.5h22.8c-1.3 8.6-5.4 13-11.4 13s-10.1-4.4-11.4-13z" fill="#e7a9b9" />
      <path d="M32 35v13" stroke="#f6e7c8" strokeWidth="4" strokeLinecap="round" />
      <path d="M22.5 54h19" stroke="#d4af6a" strokeWidth="4" strokeLinecap="round" />
    </svg>
  );
}
