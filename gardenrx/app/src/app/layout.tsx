import type { Metadata, Viewport } from 'next';
import { Hanken_Grotesk, Space_Grotesk, JetBrains_Mono } from 'next/font/google';
import Link from 'next/link';
import { Leaf, Settings } from 'lucide-react';
import { Suspense } from 'react';
import { Sidebar } from '@/components/shell/sidebar';
import { MobileNav } from '@/components/shell/mobile-nav';
import { WeatherChip } from '@/components/shell/weather-chip';
import { Clock } from '@/components/shell/clock';
import { ThemeSwitcher } from '@/components/theme-switcher';
import { ThemeScript } from '@/components/theme-script';
import { SearchWrapper } from '@/components/search-wrapper';
import { ToastProvider } from '@/components/ui/toast';
import { fetchAppSettings } from '@/lib/queries';
import { resolveServerTheme } from '@/lib/settings';
import './globals.css';

const hanken = Hanken_Grotesk({
  variable: '--font-body',
  subsets: ['latin'],
  display: 'swap',
});

const spaceGrotesk = Space_Grotesk({
  variable: '--font-display',
  subsets: ['latin'],
  display: 'swap',
});

const jetbrainsMono = JetBrains_Mono({
  variable: '--font-mono',
  subsets: ['latin'],
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'GardenRX',
  description: 'Spray decision engine for home orchards',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f7f9f8' },
    { media: '(prefers-color-scheme: dark)', color: '#0f1714' },
  ],
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const settings = await fetchAppSettings();
  const theme = resolveServerTheme(settings.theme_mode);

  return (
    <html
      lang="en"
      data-theme={theme}
      data-theme-mode={settings.theme_mode}
      data-figs={settings.figures}
      className={`${hanken.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable} antialiased`}
    >
      <body>
        <ThemeScript mode={settings.theme_mode} />
        <ToastProvider>
          <div className="app">
            <Sidebar settings={settings} />
            <div className="main">
              <header className="topbar">
                <div className="max-[499px]:hidden min-[881px]:hidden">
                  <Clock />
                </div>
                <Link
                  href="/"
                  className="flex items-center gap-2 min-[881px]:hidden"
                  aria-label="GardenRX — Today"
                >
                  <span className="brand-mark size-8">
                    <Leaf className="size-[18px]" />
                  </span>
                  <span className="brand-name text-base max-[379px]:hidden">GardenRx</span>
                </Link>
                <div className="topbar-spacer" />
                {settings.weather_bar && <WeatherChip />}
                <Suspense fallback={null}>
                  <SearchWrapper />
                </Suspense>
                <Link
                  href="/settings"
                  aria-label="Settings"
                  className="grid size-9 place-items-center rounded-full text-ink-2 transition-colors hover:bg-paper-2 min-[881px]:hidden"
                >
                  <Settings className="size-[18px]" />
                </Link>
                <div className="min-[881px]:hidden">
                  <ThemeSwitcher settings={settings} />
                </div>
              </header>
              {children}
            </div>
            <MobileNav />
          </div>
        </ToastProvider>
      </body>
    </html>
  );
}
