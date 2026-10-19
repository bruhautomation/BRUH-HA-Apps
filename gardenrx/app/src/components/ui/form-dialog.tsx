'use client';

import * as React from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

interface FormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Optional max-width class override (default "sm:max-w-sm") */
  className?: string;
  children: React.ReactNode;
  /** Footer content. If omitted, no footer is rendered. */
  footer?: React.ReactNode;
}

/**
 * Reusable dialog wrapper for forms.
 *
 * Standardizes the Dialog > DialogContent > DialogHeader > DialogTitle pattern
 * that is repeated across crop-list, harvest-tracker, garden-map, etc.
 *
 * @example
 * <FormDialog open={open} onOpenChange={setOpen} title="Add Crop">
 *   <form> ... </form>
 *   <FormDialog.Footer>
 *     <Button>Save</Button>
 *   </FormDialog.Footer>
 * </FormDialog>
 */
export function FormDialog({
  open,
  onOpenChange,
  title,
  className,
  children,
  footer,
}: FormDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={`rounded-xl ${className ?? 'sm:max-w-sm'}`}>
        <DialogHeader>
          <DialogTitle className="text-xl font-heading font-semibold tracking-tight">
            {title}
          </DialogTitle>
        </DialogHeader>
        {children}
        {footer && <DialogFooter>{footer}</DialogFooter>}
      </DialogContent>
    </Dialog>
  );
}

/**
 * Convenience confirm dialog for delete/destructive actions.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = 'Delete',
  confirmVariant = 'destructive',
  onConfirm,
  loading,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel?: string;
  confirmVariant?: 'destructive' | 'default';
  onConfirm: () => void;
  loading?: boolean;
}) {
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant={confirmVariant} onClick={onConfirm} disabled={loading}>
            {loading ? '...' : confirmLabel}
          </Button>
        </>
      }
    >
      <p className="text-sm text-muted-foreground">{description}</p>
    </FormDialog>
  );
}
