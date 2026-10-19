import { FlaskConical, Palette } from 'lucide-react';
import { fetchAppSettings } from '@/lib/queries';
import { ThemeSwitcher } from '@/components/theme-switcher';
import { SprayerTankSetting } from '@/components/settings/sprayer-tank-setting';

export const dynamic = 'force-dynamic';

export default async function SettingsPage() {
  const settings = await fetchAppSettings();

  return (
    <div className="page">
      <div className="section-title">
        <h2>Settings</h2>
        <span className="meta">App preferences</span>
      </div>

      <div className="mx-auto max-w-2xl space-y-[var(--gap)]">
        <div className="card panel">
          <div className="panel-h">
            <FlaskConical className="size-[18px] text-leaf" />
            <h3>Sprayer</h3>
          </div>
          <SprayerTankSetting />
        </div>

        <div className="card panel">
          <div className="panel-h">
            <Palette className="size-[18px] text-leaf" />
            <h3>Appearance</h3>
          </div>
          <ThemeSwitcher settings={settings} />
        </div>
      </div>
    </div>
  );
}
