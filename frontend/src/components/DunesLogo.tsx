/** The 36 Dunes mark (from the 36 Dunes site's icon): three gold dunes on a dark tile. */
export default function DunesLogo({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" className="inline-block shrink-0">
      <rect width="64" height="64" rx="14" fill="#13151C" />
      <path d="M6 24 C 16 10, 26 10, 34 19 C 38 23.5, 32 27, 28 23 C 37 13, 49 12, 58 21" stroke="#E0B25E" strokeWidth="3.4" strokeLinecap="round" fill="none" opacity="0.55" />
      <path d="M6 33 C 18 19, 30 19, 39 29 C 43 33.5, 36 36.5, 32 33 C 42 23, 54 22, 62 31" stroke="#E0B25E" strokeWidth="3.4" strokeLinecap="round" fill="none" opacity="0.78" />
      <path d="M6 43 C 20 31, 32 31, 42 40 C 50 46.5, 60 46.5, 62 41" stroke="#E0B25E" strokeWidth="3.6" strokeLinecap="round" fill="none" />
    </svg>
  );
}
