import type { Metadata, Viewport } from 'next';
import { Inter, Outfit } from 'next/font/google';

import { FittingRoomProvider } from '@/state/fitting-room-context';
import { StoreProvider } from '@/state/store-context';
import { PRODUCTS } from '@/data/catalog';

import './globals.css';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
});

const outfit = Outfit({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-outfit',
  display: 'swap',
});

const BRAND = process.env.NEXT_PUBLIC_STORE_NAME || 'STORE';

export const metadata: Metadata = {
  title: `${BRAND} — New Arrivals`,
  description:
    'A premium fashion storefront with an AI virtual fitting room: pick a piece, add your photo, and see the look before you buy.',
};

export const viewport: Viewport = {
  themeColor: '#0b0b0d',
  colorScheme: 'dark',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${outfit.variable}`}>
      <body className="antialiased">
        <StoreProvider>
          <FittingRoomProvider catalog={PRODUCTS}>{children}</FittingRoomProvider>
        </StoreProvider>
      </body>
    </html>
  );
}
