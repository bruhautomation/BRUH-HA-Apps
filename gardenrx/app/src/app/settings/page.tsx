import { FlaskConical, Palette } from 'lucide-react';
import { fetchAppSettings } from '@/lib/queries';
import { ThemeSwitcher } from '@/components/theme-switcher';
import { SprayerTankSetting } from '@/components/settings/sprayer-tank-setting';
import { PageShell } from '@/components/ui/page-shell';
import { SectionHeader } from '@/components/ui/section-header';

export const dynamic = 'force-dynamic';

export default async function SettingsPage() {
  const settings = await fetchAppSettings();

  return (
    <PageShell width="narrow" title="Settings" meta="App preferences">
      <div className="stack">
        <div className="card panel">
          <SectionHeader
            inCard
            as="h2"
            icon={<FlaskConical className="size-4 text-leaf" />}
            title="Sprayer"
          />
          <SprayerTankSetting />
        </div>

        <div className="card panel">
          <SectionHeader
            inCard
            as="h2"
            icon={<Palette className="size-4 text-leaf" />}
            title="Appearance"
          />
          <ThemeSwitcher settings={settings} />
        </div>
      </div>
    </PageShell>
  );
}
