'use client';

import { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react';
import { X, Check, TriangleAlert, Info } from 'lucide-react';

type ToastVariant = 'success' | 'error' | 'info';
type ToastAction = { label: string; onClick: () => void };

export type ToastOptions = {
  title: string;
  description?: string;
  variant?: ToastVariant;
  /** Optional inline action button (e.g. "Undo"). */
  action?: ToastAction;
  /** Auto-dismiss after this many ms. 0 keeps it until dismissed. */
  duration?: number;
};

type ToastRecord = ToastOptions & { id: number };

type ToastContextValue = {
  toast: (opts: ToastOptions) => number;
  dismiss: (id: number) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within <ToastProvider>');
  return ctx;
}

let counter = 0;

const ICONS: Record<ToastVariant, typeof Check> = {
  success: Check,
  error: TriangleAlert,
  info: Info,
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const tm = timers.current.get(id);
    if (tm) {
      clearTimeout(tm);
      timers.current.delete(id);
    }
  }, []);

  const toast = useCallback(
    (opts: ToastOptions) => {
      const id = ++counter;
      setToasts((prev) => [...prev, { ...opts, id }]);
      // Errors and actionable toasts linger so they aren't missed mid-task.
      const duration =
        opts.duration ?? (opts.action ? 8000 : opts.variant === 'error' ? 6000 : 3800);
      if (duration > 0) {
        timers.current.set(
          id,
          setTimeout(() => dismiss(id), duration)
        );
      }
      return id;
    },
    [dismiss]
  );

  // Clear any pending timers if the provider unmounts.
  useEffect(() => {
    const map = timers.current;
    return () => map.forEach((tm) => clearTimeout(tm));
  }, []);

  return (
    <ToastContext.Provider value={{ toast, dismiss }}>
      {children}
      <div className="toast-viewport" role="region" aria-label="Notifications">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: ToastRecord; onDismiss: () => void }) {
  const variant = toast.variant ?? 'info';
  const Icon = ICONS[variant];
  return (
    <div
      className={`toast toast-${variant}`}
      role={variant === 'error' ? 'alert' : 'status'}
      aria-live={variant === 'error' ? 'assertive' : 'polite'}
    >
      <span className="toast-ico" aria-hidden="true">
        <Icon className="size-[15px]" />
      </span>
      <div className="toast-body">
        <p className="toast-title">{toast.title}</p>
        {toast.description && <p className="toast-desc">{toast.description}</p>}
      </div>
      {toast.action && (
        <button
          type="button"
          className="toast-action"
          onClick={() => {
            toast.action!.onClick();
            onDismiss();
          }}
        >
          {toast.action.label}
        </button>
      )}
      <button type="button" className="toast-close" onClick={onDismiss} aria-label="Dismiss">
        <X className="size-3.5" />
      </button>
    </div>
  );
}
