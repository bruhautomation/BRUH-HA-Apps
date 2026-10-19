'use client';

import { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import type {
  GardenZone,
  GardenRegion,
  GardenTemplate,
  Variety,
  Crop,
  CropGroup,
  RegionCell,
  RegionType,
} from '@/lib/database.types';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { ConfirmDialog, FormDialog } from '@/components/ui/form-dialog';
import { createClient } from '@/lib/db/client';
import {
  Plus,
  Trash2,
  ChevronDown,
  Maximize2,
  Minimize2,
  Pencil,
  Copy,
  X,
  ZoomIn,
  ZoomOut,
  RotateCcw,
  RotateCw,
  MousePointer2,
  Eraser,
  Merge,
  Square,
  ExternalLink,
  LayoutTemplate,
  Locate,
  Settings2,
  Undo2,
  Redo2,
} from 'lucide-react';
import Link from 'next/link';

const CELL_PX = 8;
const FT_PER_CELL = 0.5;
const MIN_ZOOM = 0.3;
const MAX_ZOOM = 8;
const ZOOM_STEP = 0.15;

// Botanical field-journal palette — see src/lib/crop-colors.ts for the canonical
// source. The same tones drive pills/badges across the rest of the app.
import { COLOR_PRESETS, BORDER_PRESETS, colorsForCrop } from '@/lib/crop-colors';

/** Slight translucency on fills so grid lines and overlapping items remain readable */
const FILL_ALPHA = 0.82;

type Tool = 'draw' | 'select' | 'pan' | 'eraser';

interface Props {
  zones: GardenZone[];
  regions: GardenRegion[];
  templates: GardenTemplate[];
  varieties: Variety[];
  crops: Crop[];
  cropGroups: CropGroup[];
}

const TREE_GROUP_NAMES = new Set(['Pome Fruit', 'Stone Fruit']);

export function GardenMap({ zones, regions, templates, varieties, crops, cropGroups }: Props) {
  const router = useRouter();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const [activeZoneId, setActiveZoneId] = useState<number | null>(zones[0]?.id ?? null);
  const [fullscreen, setFullscreen] = useState(false);
  const [saving, setSaving] = useState(false);

  // Map mode — "view" is browse-only (pan, zoom, click regions to learn about
  // them). "edit" unlocks every mutation (add, draw, move, eraser, merge, etc.).
  // Default to view so looking at the garden doesn't risk accidental edits.
  const [mapMode, setMapMode] = useState<'view' | 'edit'>('view');

  // Tool state — default to "select" so dragging empty space pans natively
  // and clicking a region selects it. "+ Add" button enters draw mode for
  // one box, then snaps back to select (see handlePointerUp).
  const [activeTool, setActiveTool] = useState<Tool>('select');

  // Undo / redo — snapshot-based. Each entry is the list of regions in the
  // active zone at the moment a mutation was about to happen. Capped at 50.
  const [undoStack, setUndoStack] = useState<GardenRegion[][]>([]);
  const [redoStack, setRedoStack] = useState<GardenRegion[][]>([]);

  // Current value of the "What is this?" picker in the region dialog. Tracked
  // as state so the Variety picker can filter to just the selected crop.
  const [typeSelection, setTypeSelection] = useState<string>('planting');

  // Colors are controlled so picking a crop can auto-pick a stable palette
  // entry. User can still override by clicking a swatch.
  const [selectedColor, setSelectedColor] = useState<string>(COLOR_PRESETS[0]);
  const [selectedBorder, setSelectedBorder] = useState<string>(BORDER_PRESETS[0]);

  // Space-to-pan — holding space overrides any tool with pan behaviour
  const [spaceHeld, setSpaceHeld] = useState(false);

  // Zoom & pan
  const [zoom, setZoom] = useState(1);
  const [panOffset, setPanOffset] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });

  // Refs for zoom/pan (needed by native event listeners)
  const zoomRef = useRef(zoom);
  useEffect(() => {
    zoomRef.current = zoom;
  }, [zoom]);
  const panOffsetRef = useRef(panOffset);
  useEffect(() => {
    panOffsetRef.current = panOffset;
  }, [panOffset]);

  // True once the user has deliberately moved the view (wheel/pinch zoom, pan,
  // zoom buttons). While false, container resizes re-fit the map automatically.
  const userAdjustedView = useRef(false);

  // Fit-to-view zoom (full grid visible), kept in state for the % readout.
  const [fitZoomBase, setFitZoomBase] = useState(1);

  // Bumped by resetZoom() to force a refit on demand.
  const [refitTick, setRefitTick] = useState(0);

  // Multi-touch pinch state: pointers currently down on the canvas, plus the
  // zoom/pan snapshot taken the moment the second finger landed.
  const activePointers = useRef(new Map<number, { x: number; y: number }>());
  const pinchStart = useRef<{
    dist: number;
    mid: { x: number; y: number };
    zoom: number;
    pan: { x: number; y: number };
  } | null>(null);

  // Dialogs
  const [addZoneOpen, setAddZoneOpen] = useState(false);
  const [editZone, setEditZone] = useState<GardenZone | null>(null);
  const [zoneDeleteConfirm, setZoneDeleteConfirm] = useState<GardenZone | null>(null);
  const [editRegion, setEditRegion] = useState<GardenRegion | null>(null);
  const [newRect, setNewRect] = useState<{ x: number; y: number; w: number; h: number } | null>(
    null
  );
  const [stampTemplate, setStampTemplate] = useState<GardenTemplate | null>(null);
  const [stampRepeat, setStampRepeat] = useState<{
    count: number;
    spacingCells: number;
    direction: 'row' | 'col';
  }>({ count: 1, spacingCells: 0, direction: 'row' });
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false);
  const [editTemplate, setEditTemplate] = useState<GardenTemplate | null>(null);
  const [templateDeleteConfirm, setTemplateDeleteConfirm] = useState<GardenTemplate | null>(null);

  // Selection state (multi-select with shift+click in select mode)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  // Clipboard for copy/paste
  const [clipboard, setClipboard] = useState<GardenRegion[]>([]);

  // Interaction state
  const [dragMode, setDragMode] = useState<'none' | 'draw' | 'move'>('none');
  const [drawStart, setDrawStart] = useState<{ x: number; y: number } | null>(null);
  const [drawEnd, setDrawEnd] = useState<{ x: number; y: number } | null>(null);
  const [movingRegionId, setMovingRegionId] = useState<number | null>(null);
  const [moveOffset, setMoveOffset] = useState({ dx: 0, dy: 0 });
  const [holdTimer, setHoldTimer] = useState<ReturnType<typeof setTimeout> | null>(null);
  // Tracks the raw client pixel where the pointer went down. Used to cancel the
  // long-press-to-edit timer the moment the user actually starts dragging,
  // measured in display pixels rather than whole grid cells (which may be many
  // pixels apart at high zoom and led to the edit dialog popping up mid-drag).
  const pointerStartClient = useRef<{ x: number; y: number } | null>(null);
  const [stampPos, setStampPos] = useState<{ x: number; y: number } | null>(null);

  const activeZone = zones.find((z) => z.id === activeZoneId);
  const zoneRegions = useMemo(
    () => regions.filter((r) => r.zone_id === activeZoneId).sort((a, b) => a.z_index - b.z_index),
    [regions, activeZoneId]
  );

  const zoneRows = activeZone?.rows ?? 100;
  const zoneCols = activeZone?.cols ?? 100;
  const gridW = zoneCols * CELL_PX;
  const gridH = zoneRows * CELL_PX;

  // Variety map for O(1) lookups
  const varietyMap = useMemo(() => new Map(varieties.map((v) => [v.id, v])), [varieties]);

  // Reset zoom/pan/selection when switching zones
  useEffect(() => {
    setZoom(1);
    setPanOffset({ x: 0, y: 0 });
    setSelectedIds(new Set());
    userAdjustedView.current = false;
  }, [activeZoneId]);

  // Fit-to-container, responsive. A ResizeObserver (plus window resize, for
  // viewport-height changes the observer can't see) measures the container and
  // fits the whole grid — respecting width AND available height (container
  // height in fullscreen; 60% of viewport otherwise, matching the container's
  // maxHeight) — then centers it. Runs on mount, zone change, fullscreen
  // toggle, zone resize, and every container resize until the user zooms or
  // pans manually; the Fit button clears that flag to re-engage.
  //
  // Everything here reads the DOM directly and writes state value-stably
  // (primitives / equality-preserving updaters), so observer echoes triggered
  // by the canvas resizing can never feed back into a render loop.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const applyFit = () => {
      const cw = el.clientWidth;
      const chh = el.clientHeight;
      const vh = window.innerHeight;
      if (cw === 0) return;
      const heightBudget = fullscreen ? chh || vh : vh * 0.6;
      const fitRaw = Math.min(cw / gridW, heightBudget > 0 ? heightBudget / gridH : Infinity);
      const base = fitRaw > 0 && Number.isFinite(fitRaw) ? fitRaw : 1;
      setFitZoomBase((f) => (f === base ? f : base));
      if (userAdjustedView.current) return;
      const fitZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, base));
      const tx = Math.max(0, (cw - gridW * fitZoom) / 2);
      const ty = fullscreen ? Math.max(0, (chh - gridH * fitZoom) / 2) : 0;
      setZoom((z) => (z === fitZoom ? z : fitZoom));
      setPanOffset((p) => (p.x === tx && p.y === ty ? p : { x: tx, y: ty }));
    };
    applyFit();
    const ro = new ResizeObserver(applyFit);
    ro.observe(el);
    window.addEventListener('resize', applyFit);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', applyFit);
    };
  }, [fullscreen, activeZoneId, gridW, gridH, refitTick]);

  // Keyboard shortcuts
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      // Don't capture when typing in inputs
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement
      )
        return;

      // Mutating shortcuts only work in edit mode — view mode is read-only,
      // matching the toolbar (which hides all mutation controls in view mode).
      const canEdit = mapMode === 'edit';

      // Undo / redo
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') {
        if (!canEdit) return;
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
        return;
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'y') {
        if (!canEdit) return;
        e.preventDefault();
        redo();
        return;
      }

      // Copy/paste shortcuts
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'c') {
        // Copy selected regions to clipboard
        const selected = zoneRegions.filter((r) => selectedIds.has(r.id));
        if (selected.length > 0) {
          e.preventDefault();
          setClipboard(selected);
        }
        return;
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'v') {
        if (!canEdit) return;
        if (clipboard.length > 0) {
          e.preventDefault();
          duplicateRegions(clipboard);
        }
        return;
      }

      // Space = temporary pan while held
      if (e.key === ' ' && !spaceHeld) {
        e.preventDefault();
        setSpaceHeld(true);
        return;
      }

      switch (e.key.toLowerCase()) {
        case 'a':
          if (!canEdit) break;
          setActiveTool('draw');
          setStampTemplate(null);
          setStampPos(null);
          setStampRepeat({ count: 1, spacingCells: 0, direction: 'row' });
          break;
        case 'd':
          if (!canEdit) break;
          setActiveTool('draw');
          setStampTemplate(null);
          setStampPos(null);
          setStampRepeat({ count: 1, spacingCells: 0, direction: 'row' });
          break;
        case 'v':
          if (!canEdit) break;
          setActiveTool('select');
          setStampTemplate(null);
          setStampPos(null);
          setStampRepeat({ count: 1, spacingCells: 0, direction: 'row' });
          break;
        case 'e':
          if (!canEdit) break;
          setActiveTool('eraser');
          setStampTemplate(null);
          setStampPos(null);
          setStampRepeat({ count: 1, spacingCells: 0, direction: 'row' });
          break;
        case 'escape':
          setStampTemplate(null);
          setStampPos(null);
          setSelectedIds(new Set());
          setActiveTool('select');
          break;
        case 'delete':
        case 'backspace': {
          if (canEdit && selectedIds.size > 0) {
            e.preventDefault();
            const ids = [...selectedIds];
            if (ids.length === 1) {
              setDeleteConfirm(ids[0]);
            } else {
              // Delete all selected
              for (const id of ids) deleteRegion(id);
              setSelectedIds(new Set());
            }
          }
          break;
        }
        case '=':
        case '+':
          e.preventDefault();
          // Zoom centered on canvas center
          zoomCentered(ZOOM_STEP);
          break;
        case '-':
          e.preventDefault();
          zoomCentered(-ZOOM_STEP);
          break;
        case '0':
          e.preventDefault();
          resetZoom();
          break;
      }
    }
    function onKeyUp(e: KeyboardEvent) {
      if (e.key === ' ') setSpaceHeld(false);
    }
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIds, clipboard, zoneRegions, undoStack, redoStack, spaceHeld, mapMode]);

  function zoomCentered(delta: number) {
    const container = containerRef.current;
    if (!container) return;
    const oldZoom = zoomRef.current;
    const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, oldZoom + delta));
    if (newZoom === oldZoom) return;
    userAdjustedView.current = true;

    // Center of the container
    const centerX = container.clientWidth / 2;
    const centerY = container.clientHeight / 2;
    const scale = newZoom / oldZoom;
    const prev = panOffsetRef.current;
    setPanOffset({
      x: centerX - scale * (centerX - prev.x),
      y: centerY - scale * (centerY - prev.y),
    });
    setZoom(newZoom);
  }

  function resetZoom() {
    // Hand view control back to auto-fit; the fit effect re-measures and
    // applies the fitted zoom/centering.
    userAdjustedView.current = false;
    setRefitTick((t) => t + 1);
  }

  // Check if a grid coord falls inside a region's footprint (cells-aware).
  function hitsRegion(reg: GardenRegion, gx: number, gy: number): boolean {
    if (gx < reg.x || gx >= reg.x + reg.width || gy < reg.y || gy >= reg.y + reg.height)
      return false;
    if (!reg.cells || reg.cells.length === 0) return true;
    const lx = gx - reg.x;
    const ly = gy - reg.y;
    return reg.cells.some((c) => lx >= c.dx && lx < c.dx + c.dw && ly >= c.dy && ly < c.dy + c.dh);
  }

  // Stroke only the outer silhouette of a composite footprint (no internal seams).
  function strokeUnionOutline(
    ctx: CanvasRenderingContext2D,
    reg: GardenRegion,
    drawX: number,
    drawY: number
  ) {
    if (!reg.cells || reg.cells.length === 0) return;
    const occupied = new Set<string>();
    for (const c of reg.cells) {
      for (let dy = c.dy; dy < c.dy + c.dh; dy++) {
        for (let dx = c.dx; dx < c.dx + c.dw; dx++) {
          occupied.add(`${dx},${dy}`);
        }
      }
    }
    const has = (x: number, y: number) => occupied.has(`${x},${y}`);
    const INSET = 0.75;
    ctx.beginPath();
    for (const key of occupied) {
      const [dx, dy] = key.split(',').map(Number);
      const px = drawX + dx * CELL_PX;
      const py = drawY + dy * CELL_PX;
      if (!has(dx, dy - 1)) {
        ctx.moveTo(px, py + INSET);
        ctx.lineTo(px + CELL_PX, py + INSET);
      }
      if (!has(dx + 1, dy)) {
        ctx.moveTo(px + CELL_PX - INSET, py);
        ctx.lineTo(px + CELL_PX - INSET, py + CELL_PX);
      }
      if (!has(dx, dy + 1)) {
        ctx.moveTo(px, py + CELL_PX - INSET);
        ctx.lineTo(px + CELL_PX, py + CELL_PX - INSET);
      }
      if (!has(dx - 1, dy)) {
        ctx.moveTo(px + INSET, py);
        ctx.lineTo(px + INSET, py + CELL_PX);
      }
    }
    ctx.stroke();
  }

  // --- Canvas rendering ---
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // DPR + zoom-aware backing buffer so the map stays crisp at any zoom.
    // Cap the effective render scale to keep the backing buffer under ~8k px.
    const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1;
    const effectiveScale = Math.min(zoom * dpr, 8);
    const displayW = gridW * zoom;
    const displayH = gridH * zoom;
    const backingW = Math.round(gridW * effectiveScale);
    const backingH = Math.round(gridH * effectiveScale);
    if (canvas.width !== backingW) canvas.width = backingW;
    if (canvas.height !== backingH) canvas.height = backingH;
    canvas.style.width = `${displayW}px`;
    canvas.style.height = `${displayH}px`;

    // Draw in grid coordinates; ctx.setTransform scales to backing buffer.
    ctx.setTransform(effectiveScale, 0, 0, effectiveScale, 0, 0);

    // Background
    ctx.fillStyle = '#faf8f0';
    ctx.fillRect(0, 0, gridW, gridH);

    // 0.5ft grid (every cell)
    ctx.strokeStyle = 'rgba(0,0,0,0.06)';
    ctx.lineWidth = 0.5;
    for (let c = 0; c <= zoneCols; c++) {
      ctx.beginPath();
      ctx.moveTo(c * CELL_PX, 0);
      ctx.lineTo(c * CELL_PX, gridH);
      ctx.stroke();
    }
    for (let r = 0; r <= zoneRows; r++) {
      ctx.beginPath();
      ctx.moveTo(0, r * CELL_PX);
      ctx.lineTo(gridW, r * CELL_PX);
      ctx.stroke();
    }

    // 5ft grid (every 10 cells) — heavier
    ctx.strokeStyle = 'rgba(0,0,0,0.15)';
    ctx.lineWidth = 0.5;
    for (let c = 0; c <= zoneCols; c += 10) {
      ctx.beginPath();
      ctx.moveTo(c * CELL_PX, 0);
      ctx.lineTo(c * CELL_PX, gridH);
      ctx.stroke();
    }
    for (let r = 0; r <= zoneRows; r += 10) {
      ctx.beginPath();
      ctx.moveTo(0, r * CELL_PX);
      ctx.lineTo(gridW, r * CELL_PX);
      ctx.stroke();
    }

    // Draw regions (sorted by z_index — lowest first).
    // Track drawn external labels so neighbouring tiny boxes don't pile up on top of each other.
    const placedExternalLabels: Array<{ x: number; y: number; w: number; h: number }> = [];
    const labelsOverlap = (
      a: { x: number; y: number; w: number; h: number },
      b: { x: number; y: number; w: number; h: number }
    ) => !(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y);
    for (const reg of zoneRegions) {
      const rx = reg.x * CELL_PX;
      const ry = reg.y * CELL_PX;
      const rw = reg.width * CELL_PX;
      const rh = reg.height * CELL_PX;

      let drawX = rx;
      let drawY = ry;
      if (movingRegionId === reg.id && dragMode === 'move') {
        drawX = rx + moveOffset.dx * CELL_PX;
        drawY = ry + moveOffset.dy * CELL_PX;
      }

      // Footprint: either the composite sub-rects (irregular shape) or the bounding rect
      const footprint =
        reg.cells && reg.cells.length > 0
          ? reg.cells.map((c) => ({
              x: drawX + c.dx * CELL_PX,
              y: drawY + c.dy * CELL_PX,
              w: c.dw * CELL_PX,
              h: c.dh * CELL_PX,
            }))
          : [{ x: drawX, y: drawY, w: rw, h: rh }];

      // Fill — opacity depends on type. Crops are (near-)opaque so when they
      // sit on top of a trellis, the trellis shows through only where not
      // covered. Trellises use the lower alpha + a cattle-panel pattern so
      // they read as structural under/behind a crop.
      const isCrop =
        !!reg.variety_id || reg.region_type === 'tree' || reg.region_type === 'planting';
      const fillAlpha = reg.region_type === 'trellis' ? 0.55 : isCrop ? 1 : FILL_ALPHA;
      ctx.save();
      ctx.globalAlpha = fillAlpha;
      ctx.fillStyle = reg.color || '#e5e7eb';
      if (reg.region_type === 'tree') {
        ctx.beginPath();
        ctx.ellipse(drawX + rw / 2, drawY + rh / 2, rw / 2, rh / 2, 0, 0, Math.PI * 2);
        ctx.fill();
      } else {
        for (const f of footprint) ctx.fillRect(f.x, f.y, f.w, f.h);
      }
      ctx.restore();

      // Cattle-panel grid for trellises — vertical + horizontal wires at ~6"
      // spacing (1 cell = 6"). Drawn clipped to the region's footprint so it
      // follows irregular shapes.
      if (reg.region_type === 'trellis' && footprint.length > 0) {
        ctx.save();
        ctx.beginPath();
        for (const f of footprint) ctx.rect(f.x, f.y, f.w, f.h);
        ctx.clip();
        ctx.strokeStyle = reg.border_color || '#6b6e6b';
        ctx.globalAlpha = 0.55;
        ctx.lineWidth = 0.6;
        const step = CELL_PX; // 1 cell = 0.5 ft ≈ 6 in — matches common cattle panel mesh
        // Verticals across the whole region's bounding box, clipped above
        const minX = Math.min(...footprint.map((f) => f.x));
        const maxX = Math.max(...footprint.map((f) => f.x + f.w));
        const minY = Math.min(...footprint.map((f) => f.y));
        const maxY = Math.max(...footprint.map((f) => f.y + f.h));
        for (let x = Math.ceil(minX / step) * step; x <= maxX; x += step) {
          ctx.beginPath();
          ctx.moveTo(x + 0.5, minY);
          ctx.lineTo(x + 0.5, maxY);
          ctx.stroke();
        }
        for (let y = Math.ceil(minY / step) * step; y <= maxY; y += step) {
          ctx.beginPath();
          ctx.moveTo(minX, y + 0.5);
          ctx.lineTo(maxX, y + 0.5);
          ctx.stroke();
        }
        ctx.restore();
      }

      // Border — draw the silhouette around the union of sub-rects (no internal seams)
      if (reg.border_color) {
        ctx.strokeStyle = reg.border_color;
        ctx.lineWidth = 1.5;
        if (reg.region_type === 'tree') {
          ctx.beginPath();
          ctx.ellipse(drawX + rw / 2, drawY + rh / 2, rw / 2, rh / 2, 0, 0, Math.PI * 2);
          ctx.stroke();
        } else if (footprint.length === 1) {
          const f = footprint[0];
          ctx.strokeRect(f.x + 0.75, f.y + 0.75, f.w - 1.5, f.h - 1.5);
        } else {
          strokeUnionOutline(ctx, reg, drawX, drawY);
        }
      }

      // Trellises are hardscape — they read as "gray thing here", the legend
      // names them if you need to know which. Skip labelling so nearby plant
      // labels stay readable.
      if (reg.region_type === 'trellis') continue;

      // Label — measure-first strategy: never use fillText's maxWidth (it squeezes
      // glyphs and becomes unreadable). Instead: pick the largest font that fits,
      // truncate with an ellipsis if still too wide, or fall back to an external
      // label when the box can't hold anything legible.
      const v = varietyMap.get(reg.variety_id ?? -1);
      const vName = v?.name;
      const rawName = reg.name ?? '';
      // Concise primary label: prefer the variety name if the region name redundantly
      // wraps it (e.g., "Gala (Apple)" → "Gala"). Otherwise use the stored name.
      const displayLabel = (() => {
        if (
          rawName &&
          vName &&
          rawName.toLowerCase().includes(vName.toLowerCase()) &&
          rawName.length > vName.length
        ) {
          return vName;
        }
        return rawName || vName || '';
      })();
      // Only show the subtitle (variety) if it adds information the main label doesn't already carry.
      const hasDistinctVariety =
        !!vName &&
        vName.toLowerCase() !== displayLabel.toLowerCase() &&
        !displayLabel.toLowerCase().includes(vName.toLowerCase());

      if (displayLabel) {
        const innerW = rw - 4;
        const canShowInternal = rw >= 24 && rh >= 14 && innerW >= 16;
        const hasTwoLines = canShowInternal && hasDistinctVariety && rh >= 18;
        const MIN_FONT = 8;

        /** Find largest font (<=maxPx) that fits `text` in `availW`. If even MIN_FONT
         *  doesn't fit, truncate with an ellipsis at MIN_FONT. Returns null if the
         *  resulting string is too short to convey meaning (< 2 chars + ellipsis). */
        const fitText = (
          text: string,
          availW: number,
          maxPx: number,
          weight: string
        ): { text: string; px: number } | null => {
          let px = maxPx;
          while (px >= MIN_FONT) {
            ctx.font = `${weight} ${px}px "DM Sans", sans-serif`;
            if (ctx.measureText(text).width <= availW) return { text, px };
            px -= 0.5;
          }
          // Truncate at MIN_FONT
          ctx.font = `${weight} ${MIN_FONT}px "DM Sans", sans-serif`;
          let t = text;
          while (t.length > 0 && ctx.measureText(t + '…').width > availW) {
            t = t.slice(0, -1);
          }
          if (t.length < 2) return null; // not enough to be useful
          return { text: t + '…', px: MIN_FONT };
        };

        let renderedInternal = false;
        if (canShowInternal) {
          ctx.save();
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';

          const mainMax = Math.min(12, rh * (hasTwoLines ? 0.38 : 0.5));
          const mainFit = fitText(displayLabel, innerW, mainMax, '600');

          if (mainFit) {
            const midY = drawY + rh / 2;
            const labelY = hasTwoLines ? midY - mainFit.px * 0.42 : midY;
            ctx.font = `600 ${mainFit.px}px "DM Sans", sans-serif`;
            ctx.fillStyle = 'rgba(0,0,0,0.25)';
            ctx.fillText(mainFit.text, drawX + rw / 2 + 0.5, labelY + 0.5);
            ctx.fillStyle = 'rgba(0,0,0,0.7)';
            ctx.fillText(mainFit.text, drawX + rw / 2, labelY);

            if (hasTwoLines && vName) {
              const subMax = Math.max(7, mainFit.px * 0.8);
              const subFit = fitText(vName, innerW, subMax, '400');
              if (subFit) {
                ctx.font = `400 ${subFit.px}px "DM Sans", sans-serif`;
                const subY = labelY + mainFit.px * 0.95;
                ctx.fillStyle = 'rgba(0,0,0,0.15)';
                ctx.fillText(subFit.text, drawX + rw / 2 + 0.5, subY + 0.5);
                ctx.fillStyle = 'rgba(0,0,0,0.45)';
                ctx.fillText(subFit.text, drawX + rw / 2, subY);
              }
            }
            renderedInternal = true;
          }
          ctx.restore();
        }

        if (!renderedInternal) {
          // Small / too-narrow box: colored dot inside + stacked external labels.
          // We show the primary name AND the variety (when distinct) as two
          // lines. Placement tries above first, then below, picking whichever
          // doesn't collide with a previously-drawn external label.
          ctx.save();
          ctx.fillStyle = reg.border_color || reg.color || '#666';
          ctx.beginPath();
          ctx.arc(drawX + rw / 2, drawY + rh / 2, 2, 0, Math.PI * 2);
          ctx.fill();

          const nameFont = 7.5;
          const varietyFont = 6.5;
          const lineGap = 1;
          const extAvail = Math.max(80, rw + 40);

          // Truncate a line to fit the available width at a given font size.
          const truncateToFit = (text: string, px: number): string => {
            ctx.font = `500 ${px}px "DM Sans", sans-serif`;
            if (ctx.measureText(text).width <= extAvail) return text;
            let t = text;
            while (t.length > 0 && ctx.measureText(t + '…').width > extAvail) {
              t = t.slice(0, -1);
            }
            return t.length >= 2 ? t + '…' : '';
          };

          const lines: Array<{ text: string; px: number; weight: string; alpha: number }> = [];
          const nameText = truncateToFit(displayLabel, nameFont);
          if (nameText) lines.push({ text: nameText, px: nameFont, weight: '500', alpha: 0.7 });
          if (hasDistinctVariety && vName) {
            const vText = truncateToFit(vName, varietyFont);
            if (vText) lines.push({ text: vText, px: varietyFont, weight: '400', alpha: 0.5 });
          }

          if (lines.length > 0) {
            const cx = drawX + rw / 2;
            const pad = 1.5;
            // Total block height: sum of line heights + gaps
            const blockH = lines.reduce((s, l, i) => s + l.px + (i > 0 ? lineGap : 0), 0);
            // Block width = widest line (after font setup)
            const maxW = lines.reduce((m, l) => {
              ctx.font = `${l.weight} ${l.px}px "DM Sans", sans-serif`;
              return Math.max(m, ctx.measureText(l.text).width);
            }, 0);

            const candidates = [
              {
                // above — block sits with its bottom at drawY-2
                x: cx - maxW / 2 - pad,
                y: drawY - blockH - 2,
                w: maxW + pad * 2,
                h: blockH + pad,
                startY: drawY - 2,
                direction: 'above' as const,
              },
              {
                // below — block starts at drawY+rh+1
                x: cx - maxW / 2 - pad,
                y: drawY + rh + 1,
                w: maxW + pad * 2,
                h: blockH + pad,
                startY: drawY + rh + 1,
                direction: 'below' as const,
              },
            ];
            // Prefer below if the box is very close to the top edge.
            if (drawY <= blockH + 4) candidates.reverse();

            const chosen = candidates.find(
              (c) => !placedExternalLabels.some((p) => labelsOverlap(c, p))
            );
            if (chosen) {
              ctx.textAlign = 'center';
              if (chosen.direction === 'above') {
                // Draw from bottom up: last line first at startY (baseline=bottom)
                let y = chosen.startY;
                for (let i = lines.length - 1; i >= 0; i--) {
                  const l = lines[i];
                  ctx.font = `${l.weight} ${l.px}px "DM Sans", sans-serif`;
                  ctx.textBaseline = 'bottom';
                  ctx.fillStyle = `rgba(0,0,0,${l.alpha * 0.3})`;
                  ctx.fillText(l.text, cx + 0.5, y + 0.5);
                  ctx.fillStyle = `rgba(0,0,0,${l.alpha})`;
                  ctx.fillText(l.text, cx, y);
                  y -= l.px + lineGap;
                }
              } else {
                // Draw top-down from startY (baseline=top)
                let y = chosen.startY;
                for (const l of lines) {
                  ctx.font = `${l.weight} ${l.px}px "DM Sans", sans-serif`;
                  ctx.textBaseline = 'top';
                  ctx.fillStyle = `rgba(0,0,0,${l.alpha * 0.3})`;
                  ctx.fillText(l.text, cx + 0.5, y + 0.5);
                  ctx.fillStyle = `rgba(0,0,0,${l.alpha})`;
                  ctx.fillText(l.text, cx, y);
                  y += l.px + lineGap;
                }
              }
              placedExternalLabels.push({ x: chosen.x, y: chosen.y, w: chosen.w, h: chosen.h });
            }
          }
          ctx.restore();
        }
      }
    }

    // Draw selection highlight on selected regions
    if (selectedIds.size > 0) {
      ctx.save();
      ctx.setLineDash([3, 2]);
      ctx.lineWidth = 2;
      ctx.strokeStyle = 'rgba(59,130,246,0.8)';
      for (const reg of zoneRegions) {
        if (!selectedIds.has(reg.id)) continue;
        let dx = reg.x * CELL_PX;
        let dy = reg.y * CELL_PX;
        if (movingRegionId === reg.id && dragMode === 'move') {
          dx += moveOffset.dx * CELL_PX;
          dy += moveOffset.dy * CELL_PX;
        }
        const dw = reg.width * CELL_PX;
        const dh = reg.height * CELL_PX;
        if (reg.region_type === 'tree') {
          ctx.beginPath();
          ctx.ellipse(dx + dw / 2, dy + dh / 2, dw / 2 + 1, dh / 2 + 1, 0, 0, Math.PI * 2);
          ctx.stroke();
        } else {
          ctx.strokeRect(dx - 1, dy - 1, dw + 2, dh + 2);
        }
      }
      ctx.setLineDash([]);
      ctx.restore();
    }

    // Draw active selection
    if (dragMode === 'draw' && drawStart && drawEnd) {
      const sx = Math.min(drawStart.x, drawEnd.x) * CELL_PX;
      const sy = Math.min(drawStart.y, drawEnd.y) * CELL_PX;
      const sw = (Math.abs(drawEnd.x - drawStart.x) + 1) * CELL_PX;
      const sh = (Math.abs(drawEnd.y - drawStart.y) + 1) * CELL_PX;
      ctx.fillStyle = 'rgba(59,130,246,0.15)';
      ctx.fillRect(sx, sy, sw, sh);
      ctx.strokeStyle = 'rgba(59,130,246,0.6)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 2]);
      ctx.strokeRect(sx, sy, sw, sh);
      ctx.setLineDash([]);

      const wFt = ((Math.abs(drawEnd.x - drawStart.x) + 1) * FT_PER_CELL).toFixed(1);
      const hFt = ((Math.abs(drawEnd.y - drawStart.y) + 1) * FT_PER_CELL).toFixed(1);
      ctx.font = "600 9px 'DM Sans', sans-serif";
      ctx.fillStyle = 'rgba(59,130,246,0.9)';
      ctx.textAlign = 'center';
      ctx.fillText(`${wFt}' × ${hFt}'`, sx + sw / 2, sy - 4);
    }

    // Stamp preview (with repeat)
    if (stampTemplate && stampPos) {
      const sw = stampTemplate.width * CELL_PX;
      const sh = stampTemplate.height * CELL_PX;
      ctx.globalAlpha = 0.5;
      for (let i = 0; i < stampRepeat.count; i++) {
        const stepSize =
          stampRepeat.direction === 'row'
            ? stampTemplate.width + stampRepeat.spacingCells
            : stampTemplate.height + stampRepeat.spacingCells;
        const ox = stampRepeat.direction === 'row' ? i * stepSize * CELL_PX : 0;
        const oy = stampRepeat.direction === 'col' ? i * stepSize * CELL_PX : 0;
        const sx = stampPos.x * CELL_PX + ox;
        const sy = stampPos.y * CELL_PX + oy;
        ctx.fillStyle = stampTemplate.color;
        ctx.fillRect(sx, sy, sw, sh);
        ctx.strokeStyle = stampTemplate.border_color;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(sx + 0.75, sy + 0.75, sw - 1.5, sh - 1.5);
      }
      ctx.globalAlpha = 1;
    }
  }, [
    zoneRegions,
    gridW,
    gridH,
    zoneRows,
    zoneCols,
    zoom,
    dragMode,
    drawStart,
    drawEnd,
    movingRegionId,
    moveOffset,
    stampTemplate,
    stampPos,
    stampRepeat,
    selectedIds,
    varietyMap,
  ]);

  useEffect(() => {
    draw();
  }, [draw]);

  // --- Pointer helpers ---
  // Compute grid cell from pointer event using CSS display size, not the
  // (DPR-scaled) backing buffer. rect.width == gridW * zoom visually.
  function canvasToGrid(e: React.PointerEvent): { x: number; y: number } | null {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const displayX = e.clientX - rect.left;
    const displayY = e.clientY - rect.top;
    const cellDisplayPx = CELL_PX * zoom;
    const x = Math.floor(displayX / cellDisplayPx);
    const y = Math.floor(displayY / cellDisplayPx);
    if (x < 0 || y < 0 || x >= zoneCols || y >= zoneRows) return null;
    return { x, y };
  }

  function regionAt(gx: number, gy: number): GardenRegion | null {
    for (let i = zoneRegions.length - 1; i >= 0; i--) {
      const r = zoneRegions[i];
      if (hitsRegion(r, gx, gy)) return r;
    }
    return null;
  }

  // --- Wheel zoom (native listener to allow preventDefault on passive) ---
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    function onWheel(e: WheelEvent) {
      e.preventDefault();
      const cont = containerRef.current;
      if (!cont) return;

      // Get cursor position relative to container
      const rect = cont.getBoundingClientRect();
      const cursorX = e.clientX - rect.left;
      const cursorY = e.clientY - rect.top;

      const oldZoom = zoomRef.current;
      const delta = e.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP;
      const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, oldZoom + delta));
      if (newZoom === oldZoom) return;
      userAdjustedView.current = true;

      // Adjust pan so the point under cursor stays fixed
      const scale = newZoom / oldZoom;
      const prev = panOffsetRef.current;
      setPanOffset({
        x: cursorX - scale * (cursorX - prev.x),
        y: cursorY - scale * (cursorY - prev.y),
      });
      setZoom(newZoom);
    }
    container.addEventListener('wheel', onWheel, { passive: false });
    return () => container.removeEventListener('wheel', onWheel);
  }, []);

  // --- Pinch zoom (touch) ---
  // Midpoint + distance of the two active pointers, relative to the container.
  function pinchGeometry(): { dist: number; mid: { x: number; y: number } } | null {
    const container = containerRef.current;
    if (!container || activePointers.current.size < 2) return null;
    const [a, b] = [...activePointers.current.values()];
    const rect = container.getBoundingClientRect();
    return {
      dist: Math.max(1, Math.hypot(b.x - a.x, b.y - a.y)),
      mid: { x: (a.x + b.x) / 2 - rect.left, y: (a.y + b.y) / 2 - rect.top },
    };
  }

  function beginPinch() {
    const geo = pinchGeometry();
    if (!geo) return;
    pinchStart.current = {
      dist: geo.dist,
      mid: geo.mid,
      zoom: zoomRef.current,
      pan: panOffsetRef.current,
    };
    // A second finger cancels any in-progress draw/move/long-press.
    if (holdTimer) {
      clearTimeout(holdTimer);
      setHoldTimer(null);
    }
    pointerStartClient.current = null;
    setDragMode('none');
    setDrawStart(null);
    setDrawEnd(null);
    setMovingRegionId(null);
    setMoveOffset({ dx: 0, dy: 0 });
    setIsPanning(false);
  }

  function updatePinch() {
    const start = pinchStart.current;
    const geo = pinchGeometry();
    if (!start || !geo) return;
    userAdjustedView.current = true;
    const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, start.zoom * (geo.dist / start.dist)));
    const scale = newZoom / start.zoom;
    // Keep the world point that was under the initial midpoint glued to the
    // current midpoint — this gives combined pinch-zoom + two-finger pan.
    setPanOffset({
      x: geo.mid.x - scale * (start.mid.x - start.pan.x),
      y: geo.mid.y - scale * (start.mid.y - start.pan.y),
    });
    setZoom(newZoom);
  }

  // --- Pointer events ---
  function handlePointerDown(e: React.PointerEvent) {
    if (e.pointerType === 'touch') {
      activePointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (activePointers.current.size === 2) {
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        beginPinch();
        return;
      }
    }

    // Global pan overrides: explicit Pan tool, OR Space held, OR middle mouse button
    if (activeTool === 'pan' || spaceHeld || e.button === 1) {
      setIsPanning(true);
      setPanStart({ x: e.clientX - panOffset.x, y: e.clientY - panOffset.y });
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      return;
    }

    const pos = canvasToGrid(e);
    if (!pos) return;

    // Stamp mode
    if (stampTemplate) {
      placeStamp(pos.x, pos.y);
      return;
    }

    // Eraser mode
    if (activeTool === 'eraser') {
      const hit = regionAt(pos.x, pos.y);
      if (hit) setDeleteConfirm(hit.id);
      return;
    }

    const hit = regionAt(pos.x, pos.y);

    if (activeTool === 'select') {
      if (!hit) {
        // Empty-space drag in select mode = pan the view (native canvas feel).
        setSelectedIds(new Set());
        setIsPanning(true);
        setPanStart({ x: e.clientX - panOffset.x, y: e.clientY - panOffset.y });
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        return;
      }
      // View mode: tapping a plant jumps to its crop page. Non-crop regions
      // (beds, trellises, structures) just get selected so you can see the
      // size/name chip. No drags, no long-press-to-edit — strictly read-only.
      if (mapMode === 'view') {
        if (hit.variety_id) {
          const v = varieties.find((vv) => vv.id === hit.variety_id);
          if (v?.crop_id) {
            router.push(`/crops/${v.crop_id}`);
            return;
          }
        }
        setSelectedIds(new Set([hit.id]));
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        return;
      }
      if (hit) {
        // Shift+click: toggle in multi-select
        if (e.shiftKey) {
          setSelectedIds((prev) => {
            const next = new Set(prev);
            if (next.has(hit.id)) next.delete(hit.id);
            else next.add(hit.id);
            return next;
          });
        } else {
          // Single click: select this one (or start move if already selected)
          if (!selectedIds.has(hit.id)) {
            setSelectedIds(new Set([hit.id]));
          }
        }
        // Long-press to edit — cancelled by pointer-move in handlePointerMove.
        pointerStartClient.current = { x: e.clientX, y: e.clientY };
        const timer = setTimeout(() => {
          setEditRegion(hit);
          setDragMode('none');
        }, 600);
        setHoldTimer(timer);
        setDragMode('move');
        setMovingRegionId(hit.id);
        setMoveOffset({ dx: 0, dy: 0 });
        setDrawStart(pos);
      }
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      return;
    }

    // Draw mode (default) — only draw new rectangles, never move
    if (hit) {
      // Long-press on existing region opens edit dialog
      pointerStartClient.current = { x: e.clientX, y: e.clientY };
      const timer = setTimeout(() => {
        setEditRegion(hit);
        setDragMode('none');
      }, 600);
      setHoldTimer(timer);
      // Short tap: do nothing (wait for hold or release)
      setDragMode('none');
      setDrawStart(pos);
    } else {
      setDragMode('draw');
      setDrawStart(pos);
      setDrawEnd(pos);
      pointerStartClient.current = { x: e.clientX, y: e.clientY };
    }

    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }

  function handlePointerMove(e: React.PointerEvent) {
    // Pinch zoom in progress — two fingers own the gesture
    if (e.pointerType === 'touch' && activePointers.current.has(e.pointerId)) {
      activePointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pinchStart.current) {
        updatePinch();
        return;
      }
    }

    // Panning
    if (isPanning) {
      userAdjustedView.current = true;
      setPanOffset({ x: e.clientX - panStart.x, y: e.clientY - panStart.y });
      return;
    }

    const pos = canvasToGrid(e);
    if (!pos) return;

    // Update stamp position
    if (stampTemplate) {
      setStampPos(pos);
      return;
    }

    // Cancel the long-press-to-edit timer the instant the user actually starts
    // dragging. We measure displacement in *display* pixels, not grid cells —
    // the grid-cell test failed when the whole drag happened inside one cell at
    // high zoom, causing the edit dialog to pop up mid-move.
    if (holdTimer && pointerStartClient.current) {
      const dx = e.clientX - pointerStartClient.current.x;
      const dy = e.clientY - pointerStartClient.current.y;
      if (dx * dx + dy * dy > 36) {
        // >6 display pixels of travel
        clearTimeout(holdTimer);
        setHoldTimer(null);
        // In the draw tool, that movement means "you meant to draw over this region".
        if (activeTool === 'draw' && dragMode === 'none') {
          setDragMode('draw');
        }
      }
    }

    if (dragMode === 'draw') {
      setDrawEnd(pos);
    } else if (dragMode === 'move' && drawStart) {
      setMoveOffset({
        dx: pos.x - drawStart.x,
        dy: pos.y - drawStart.y,
      });
    }
  }

  function handlePointerUp(e: React.PointerEvent) {
    if (e.pointerType === 'touch') {
      activePointers.current.delete(e.pointerId);
      if (pinchStart.current) {
        // End the pinch once we drop below two fingers; swallow the event so
        // the lifted finger isn't misread as a tap/draw release.
        if (activePointers.current.size < 2) pinchStart.current = null;
        try {
          (e.target as HTMLElement).releasePointerCapture(e.pointerId);
        } catch {
          /* already released */
        }
        return;
      }
    }

    // Panning
    if (isPanning) {
      setIsPanning(false);
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
      return;
    }

    if (holdTimer) {
      clearTimeout(holdTimer);
      setHoldTimer(null);
    }
    pointerStartClient.current = null;

    if (dragMode === 'draw' && drawStart && drawEnd) {
      const x = Math.min(drawStart.x, drawEnd.x);
      const y = Math.min(drawStart.y, drawEnd.y);
      const w = Math.abs(drawEnd.x - drawStart.x) + 1;
      const h = Math.abs(drawEnd.y - drawStart.y) + 1;
      if (w >= 2 || h >= 2) {
        setNewRect({ x, y, w, h });
        // Snap back to select after one draw — "Add" is a one-shot action.
        setActiveTool('select');
      }
    } else if (
      dragMode === 'move' &&
      movingRegionId &&
      (moveOffset.dx !== 0 || moveOffset.dy !== 0)
    ) {
      commitMove(movingRegionId, moveOffset.dx, moveOffset.dy);
    }

    setDragMode('none');
    setDrawStart(null);
    setDrawEnd(null);
    setMovingRegionId(null);
    setMoveOffset({ dx: 0, dy: 0 });
    (e.target as HTMLElement).releasePointerCapture(e.pointerId);
  }

  function handlePointerCancel(e: React.PointerEvent) {
    if (e.pointerType === 'touch') {
      activePointers.current.delete(e.pointerId);
      if (activePointers.current.size < 2) pinchStart.current = null;
    }
    if (holdTimer) {
      clearTimeout(holdTimer);
      setHoldTimer(null);
    }
    pointerStartClient.current = null;
    setIsPanning(false);
    setDragMode('none');
    setDrawStart(null);
    setDrawEnd(null);
    setMovingRegionId(null);
    setMoveOffset({ dx: 0, dy: 0 });
  }

  // --- Actions ---
  async function commitMove(regionId: number, dx: number, dy: number) {
    const reg = zoneRegions.find((r) => r.id === regionId);
    if (!reg) return;
    pushUndo();
    const supabase = createClient();
    const { error } = await supabase
      .from('garden_regions')
      .update({ x: reg.x + dx, y: reg.y + dy })
      .eq('id', regionId);
    if (error) console.error('Move region failed:', error);
    router.refresh();
  }

  async function placeStamp(gx: number, gy: number) {
    if (!stampTemplate || !activeZoneId) return;
    pushUndo();
    setSaving(true);
    const supabase = createClient();
    const maxZ = Math.max(0, ...zoneRegions.map((r) => r.z_index));

    const inserts = [];
    for (let i = 0; i < stampRepeat.count; i++) {
      const stepSize =
        stampRepeat.direction === 'row'
          ? stampTemplate.width + stampRepeat.spacingCells
          : stampTemplate.height + stampRepeat.spacingCells;
      const ox = stampRepeat.direction === 'row' ? i * stepSize : 0;
      const oy = stampRepeat.direction === 'col' ? i * stepSize : 0;
      inserts.push({
        zone_id: activeZoneId,
        name: stampRepeat.count > 1 ? `${stampTemplate.name} ${i + 1}` : stampTemplate.name,
        region_type: stampTemplate.element_type,
        x: gx + ox,
        y: gy + oy,
        width: stampTemplate.width,
        height: stampTemplate.height,
        color: stampTemplate.color,
        border_color: stampTemplate.border_color,
        z_index: maxZ + 1 + i,
        template_id: stampTemplate.id,
      });
    }

    const { error } = await supabase.from('garden_regions').insert(inserts);
    if (error) console.error('Place stamp failed:', error);
    setSaving(false);
    router.refresh();
  }

  async function saveAsTemplate(region: GardenRegion) {
    setSaving(true);
    const supabase = createClient();
    const { error } = await supabase.from('garden_templates').insert({
      name: region.name,
      element_type: region.region_type,
      width: region.width,
      height: region.height,
      color: region.color || '#86efac',
      border_color: region.border_color || '#059669',
    });
    if (error) console.error('Save template failed:', error);
    setSaving(false);
    setEditRegion(null);
    router.refresh();
  }

  async function updateTemplate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!editTemplate) return;
    setSaving(true);
    const supabase = createClient();
    const fd = new FormData(e.currentTarget);
    const widthFt = parseFloat(String(fd.get('width') ?? '0')) || editTemplate.width * FT_PER_CELL;
    const heightFt =
      parseFloat(String(fd.get('height') ?? '0')) || editTemplate.height * FT_PER_CELL;
    const { error } = await supabase
      .from('garden_templates')
      .update({
        name: String(fd.get('name') ?? editTemplate.name).trim() || editTemplate.name,
        element_type: String(fd.get('element_type') ?? editTemplate.element_type) as RegionType,
        width: Math.max(1, Math.round(widthFt / FT_PER_CELL)),
        height: Math.max(1, Math.round(heightFt / FT_PER_CELL)),
        color: String(fd.get('color') ?? editTemplate.color),
        border_color: String(fd.get('border_color') ?? editTemplate.border_color),
      })
      .eq('id', editTemplate.id);
    if (error) console.error('Update template failed:', error);
    setSaving(false);
    setEditTemplate(null);
    router.refresh();
  }

  async function deleteTemplate(id: number) {
    setSaving(true);
    const supabase = createClient();
    const { error } = await supabase.from('garden_templates').delete().eq('id', id);
    if (error) console.error('Delete template failed:', error);
    setSaving(false);
    setTemplateDeleteConfirm(null);
    router.refresh();
  }

  // Decode the combined Type picker value. Format is either a crop selector
  // (`crop:{cropId}`) or a plain region_type literal.
  function decodeRegionTypeSelection(
    raw: string,
    varietyIdForm: string
  ): { region_type: RegionType; variety_id: number | null } {
    if (raw.startsWith('crop:')) {
      const cropId = parseInt(raw.slice(5));
      const crop = crops.find((c) => c.id === cropId);
      const groupName = crop?.crop_group_id
        ? cropGroups.find((g) => g.id === crop.crop_group_id)?.name
        : undefined;
      const regionType = groupName && TREE_GROUP_NAMES.has(groupName) ? 'tree' : 'planting';
      // Keep variety_id only if it belongs to this crop; otherwise drop it.
      let variety_id: number | null = null;
      if (varietyIdForm) {
        const vid = parseInt(varietyIdForm);
        const v = varieties.find((vv) => vv.id === vid);
        if (v && v.crop_id === cropId) variety_id = vid;
      }
      return { region_type: regionType, variety_id };
    }
    return {
      region_type: raw as RegionType,
      variety_id: varietyIdForm ? parseInt(varietyIdForm) : null,
    };
  }

  // ── Undo / redo ────────────────────────────────────────────────────────────
  // Call pushUndo() BEFORE performing any region mutation. This records the
  // current server state of the active zone so undo can reconstruct it.
  function pushUndo() {
    if (!activeZoneId) return;
    const snap = regions.filter((r) => r.zone_id === activeZoneId);
    setUndoStack((s) => (s.length >= 50 ? [...s.slice(1), snap] : [...s, snap]));
    setRedoStack([]);
  }

  // Sync the active zone's server state to match `target` by diffing + applying
  // the minimum set of insert/update/delete operations.
  async function applySnapshot(target: GardenRegion[]) {
    if (!activeZoneId) return;
    setSaving(true);
    const supabase = createClient();
    const current = regions.filter((r) => r.zone_id === activeZoneId);
    const targetMap = new Map(target.map((r) => [r.id, r]));
    const currentMap = new Map(current.map((r) => [r.id, r]));

    const ops: Array<PromiseLike<unknown>> = [];

    // Deletions: present now, missing in target
    for (const [id] of currentMap) {
      if (!targetMap.has(id)) {
        ops.push(supabase.from('garden_regions').delete().eq('id', id));
      }
    }
    // Insertions: missing now, present in target — preserve the original ID
    for (const [id, r] of targetMap) {
      if (!currentMap.has(id)) {
        const { created_at: _ca, ...row } = r;
        void _ca;
        ops.push(supabase.from('garden_regions').insert({ ...row, id }));
      }
    }
    // Updates: present in both but differ on any field
    for (const [id, r] of targetMap) {
      const c = currentMap.get(id);
      if (c && JSON.stringify(c) !== JSON.stringify(r)) {
        const { id: _omit, created_at: _ca, ...rest } = r;
        void _omit;
        void _ca;
        ops.push(supabase.from('garden_regions').update(rest).eq('id', id));
      }
    }

    await Promise.all(ops);
    setSaving(false);
    router.refresh();
  }

  async function undo() {
    if (undoStack.length === 0 || !activeZoneId) return;
    const currentSnap = regions.filter((r) => r.zone_id === activeZoneId);
    const target = undoStack[undoStack.length - 1];
    setUndoStack((s) => s.slice(0, -1));
    setRedoStack((s) => [...s, currentSnap]);
    setSelectedIds(new Set());
    await applySnapshot(target);
  }

  async function redo() {
    if (redoStack.length === 0 || !activeZoneId) return;
    const currentSnap = regions.filter((r) => r.zone_id === activeZoneId);
    const target = redoStack[redoStack.length - 1];
    setRedoStack((s) => s.slice(0, -1));
    setUndoStack((s) => [...s, currentSnap]);
    setSelectedIds(new Set());
    await applySnapshot(target);
  }

  async function saveRegion(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!activeZoneId) return;
    pushUndo();
    setSaving(true);
    const supabase = createClient();
    const formData = new FormData(e.currentTarget);
    const name = formData.get('name') as string;
    const rawTypeSelection = (formData.get('region_type') as string) ?? 'planting';
    const varietyIdForm = (formData.get('variety_id') as string) ?? '';
    const { region_type, variety_id } = decodeRegionTypeSelection(rawTypeSelection, varietyIdForm);
    const color = formData.get('color') as string;
    const borderColor = formData.get('border_color') as string;

    if (editRegion) {
      const widthFt = formData.get('width_ft') as string;
      const heightFt = formData.get('height_ft') as string;
      const update: {
        name: string;
        region_type: RegionType;
        variety_id: number | null;
        color: string;
        border_color: string;
        width?: number;
        height?: number;
      } = {
        name,
        region_type,
        variety_id,
        color,
        border_color: borderColor,
      };
      if (widthFt) update.width = Math.round(parseFloat(widthFt) / FT_PER_CELL);
      if (heightFt) update.height = Math.round(parseFloat(heightFt) / FT_PER_CELL);
      const { error } = await supabase
        .from('garden_regions')
        .update(update)
        .eq('id', editRegion.id);
      if (error) console.error('Update region failed:', error);
      setEditRegion(null);
    } else if (newRect) {
      const maxZ = Math.max(0, ...zoneRegions.map((r) => r.z_index));
      const { error } = await supabase.from('garden_regions').insert({
        zone_id: activeZoneId,
        name,
        region_type,
        variety_id,
        x: newRect.x,
        y: newRect.y,
        width: newRect.w,
        height: newRect.h,
        color,
        border_color: borderColor,
        z_index: maxZ + 1,
      });
      if (error) console.error('Insert region failed:', error.message ?? error);
      setNewRect(null);
    }
    setSaving(false);
    router.refresh();
  }

  async function deleteRegion(id: number) {
    pushUndo();
    const supabase = createClient();
    const { error } = await supabase.from('garden_regions').delete().eq('id', id);
    if (error) console.error('Delete region failed:', error);
    setEditRegion(null);
    setDeleteConfirm(null);
    router.refresh();
  }

  async function addZone(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSaving(true);
    const supabase = createClient();
    const formData = new FormData(e.currentTarget);
    const name = formData.get('name') as string;
    const widthFt = parseFloat(formData.get('width_ft') as string) || 50;
    const heightFt = parseFloat(formData.get('height_ft') as string) || 50;
    const cols = Math.round(widthFt / FT_PER_CELL);
    const rows = Math.round(heightFt / FT_PER_CELL);
    const { data, error } = await supabase
      .from('garden_zones')
      .insert({ name, rows, cols })
      .select()
      .single();
    if (error) console.error('Insert zone failed:', error);
    setSaving(false);
    setAddZoneOpen(false);
    if (data) setActiveZoneId(data.id);
    router.refresh();
  }

  async function deleteZone(id: number) {
    const supabase = createClient();
    await supabase.from('garden_zones').delete().eq('id', id);
    setActiveZoneId(zones.find((z) => z.id !== id)?.id ?? null);
    router.refresh();
  }

  async function saveZoneEdit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!editZone) return;
    setSaving(true);
    const supabase = createClient();
    const fd = new FormData(e.currentTarget);
    const name = String(fd.get('name') ?? editZone.name).trim() || editZone.name;
    const widthFt = parseFloat(String(fd.get('width_ft') ?? '')) || editZone.cols * FT_PER_CELL;
    const heightFt = parseFloat(String(fd.get('height_ft') ?? '')) || editZone.rows * FT_PER_CELL;
    const cols = Math.max(1, Math.round(widthFt / FT_PER_CELL));
    const rows = Math.max(1, Math.round(heightFt / FT_PER_CELL));
    const { error } = await supabase
      .from('garden_zones')
      .update({ name, rows, cols })
      .eq('id', editZone.id);
    if (error) console.error('Update zone failed:', error);
    setSaving(false);
    setEditZone(null);
    router.refresh();
  }

  // Recenter + fit-to-content: zoom and pan so the union of all regions is centered in the viewport.
  function centerOnContent() {
    if (!containerRef.current) return;
    if (zoneRegions.length === 0) {
      resetZoom();
      return;
    }
    const minX = Math.min(...zoneRegions.map((r) => r.x));
    const minY = Math.min(...zoneRegions.map((r) => r.y));
    const maxX = Math.max(...zoneRegions.map((r) => r.x + r.width));
    const maxY = Math.max(...zoneRegions.map((r) => r.y + r.height));
    const bboxWpx = Math.max(1, (maxX - minX) * CELL_PX);
    const bboxHpx = Math.max(1, (maxY - minY) * CELL_PX);
    const cw = containerRef.current.clientWidth;
    const ch = containerRef.current.clientHeight || cw;
    const pad = 32;
    const fitZoom = Math.max(
      MIN_ZOOM,
      Math.min(MAX_ZOOM, (cw - pad * 2) / bboxWpx, (ch - pad * 2) / bboxHpx)
    );
    const centerXpx = ((minX + maxX) / 2) * CELL_PX * fitZoom;
    const centerYpx = ((minY + maxY) / 2) * CELL_PX * fitZoom;
    userAdjustedView.current = true;
    setZoom(fitZoom);
    setPanOffset({ x: cw / 2 - centerXpx, y: ch / 2 - centerYpx });
  }

  async function rotateSelected() {
    if (selectedIds.size === 0) return;
    const targets = zoneRegions.filter((r) => selectedIds.has(r.id));
    if (targets.length === 0) return;
    pushUndo();
    setSaving(true);
    const supabase = createClient();
    for (const r of targets) {
      const W = r.width;
      const H = r.height;
      const newW = H;
      const newH = W;
      // Rotate around the region's centre so it stays anchored visually.
      const newX = Math.round(r.x + (W - newW) / 2);
      const newY = Math.round(r.y + (H - newH) / 2);
      let newCells: RegionCell[] | null = null;
      if (r.cells && r.cells.length > 0) {
        // 90° clockwise: (dx, dy, dw, dh) within W×H box becomes
        // (H - dy - dh, dx, dh, dw) within H×W box.
        newCells = r.cells.map((c) => ({
          dx: H - c.dy - c.dh,
          dy: c.dx,
          dw: c.dh,
          dh: c.dw,
        }));
      }
      const { error } = await supabase
        .from('garden_regions')
        .update({ x: newX, y: newY, width: newW, height: newH, cells: newCells })
        .eq('id', r.id);
      if (error) console.error('Rotate region failed:', error);
    }
    setSaving(false);
    router.refresh();
  }

  async function mergeSelected() {
    if (selectedIds.size < 2) return;
    if (!activeZoneId) return;
    const selected = zoneRegions.filter((r) => selectedIds.has(r.id));
    if (selected.length < 2) return;
    pushUndo();

    // Bounding box (absolute grid coords)
    const minX = Math.min(...selected.map((r) => r.x));
    const minY = Math.min(...selected.map((r) => r.y));
    const maxX = Math.max(...selected.map((r) => r.x + r.width));
    const maxY = Math.max(...selected.map((r) => r.y + r.height));

    // Build the composite footprint: union of each source's sub-rects (or its
    // own bounding rect if it was a plain rectangle), rebased to the new (minX,minY).
    const rawCells: RegionCell[] = [];
    for (const r of selected) {
      const subs =
        r.cells && r.cells.length > 0 ? r.cells : [{ dx: 0, dy: 0, dw: r.width, dh: r.height }];
      for (const s of subs) {
        rawCells.push({
          dx: r.x + s.dx - minX,
          dy: r.y + s.dy - minY,
          dw: s.dw,
          dh: s.dh,
        });
      }
    }
    // Collapse to a cell-grid set, then re-emit as one sub-rect per cell.
    // Simple and works for any irregular shape; renderer hides internal seams.
    const occ = new Set<string>();
    for (const c of rawCells) {
      for (let dy = c.dy; dy < c.dy + c.dh; dy++) {
        for (let dx = c.dx; dx < c.dx + c.dw; dx++) {
          occ.add(`${dx},${dy}`);
        }
      }
    }
    const cells: RegionCell[] = [...occ].map((k) => {
      const [dx, dy] = k.split(',').map(Number);
      return { dx, dy, dw: 1, dh: 1 };
    });

    const primary = selected[0];
    const maxZ = Math.max(0, ...zoneRegions.map((r) => r.z_index));

    setSaving(true);
    const supabase = createClient();

    const { error: insertErr } = await supabase.from('garden_regions').insert({
      zone_id: activeZoneId,
      name: selected.map((r) => r.name).join(' + '),
      region_type: primary.region_type,
      variety_id: primary.variety_id,
      x: minX,
      y: minY,
      width: maxX - minX,
      height: maxY - minY,
      color: primary.color,
      border_color: primary.border_color,
      z_index: maxZ + 1,
      cells,
    });
    if (insertErr) {
      console.error('Merge insert failed:', insertErr);
      setSaving(false);
      return;
    }

    for (const r of selected) {
      await supabase.from('garden_regions').delete().eq('id', r.id);
    }

    setSelectedIds(new Set());
    setSaving(false);
    router.refresh();
  }

  async function duplicateRegions(regionsToDuplicate: GardenRegion[]) {
    if (!activeZoneId || regionsToDuplicate.length === 0) return;
    pushUndo();
    setSaving(true);
    const supabase = createClient();
    const maxZ = Math.max(0, ...zoneRegions.map((r) => r.z_index));
    const offsetCells = 4; // 2 ft offset

    const inserts = regionsToDuplicate.map((r, i) => ({
      zone_id: activeZoneId,
      name: r.name,
      region_type: r.region_type,
      variety_id: r.variety_id,
      x: r.x + offsetCells,
      y: r.y + offsetCells,
      width: r.width,
      height: r.height,
      color: r.color,
      border_color: r.border_color,
      z_index: maxZ + 1 + i,
    }));

    const { error } = await supabase.from('garden_regions').insert(inserts);
    if (error) console.error('Duplicate regions failed:', error);
    setSaving(false);
    setSelectedIds(new Set());
    router.refresh();
  }

  async function bringToFront(id: number) {
    const maxZ = Math.max(0, ...zoneRegions.map((r) => r.z_index));
    const supabase = createClient();
    await supabase
      .from('garden_regions')
      .update({ z_index: maxZ + 1 })
      .eq('id', id);
    router.refresh();
  }

  async function sendToBack(id: number) {
    const minZ = Math.min(0, ...zoneRegions.map((r) => r.z_index));
    const supabase = createClient();
    await supabase
      .from('garden_regions')
      .update({ z_index: minZ - 1 })
      .eq('id', id);
    router.refresh();
  }

  // Legend — grouped by category. Plants = anything with a variety assigned.
  // Beds = planting / tree regions that haven't been linked to a specific crop.
  // Trellises = trellis type. Structures = path / structure / landmark.
  const legend = useMemo(() => {
    type Entry = { name: string; color: string; border: string };
    const plants = new Map<string, Entry>();
    const beds = new Map<string, Entry>();
    const trellises = new Map<string, Entry>();
    const structures = new Map<string, Entry>();
    // Strip parenthetical suffixes like "Cherokee Purple (Tomatoes)" → "Cherokee Purple"
    // and fall back to the variety name when the stored region name is redundant.
    const cleanName = (r: GardenRegion): string => {
      const v = varieties.find((vv) => vv.id === (r.variety_id ?? -1));
      const stripped = (r.name ?? '').replace(/\s*\([^)]*\)\s*$/, '').trim();
      return stripped || v?.name || r.name || '';
    };
    for (const r of zoneRegions) {
      if (!r.color) continue;
      const displayName = cleanName(r);
      if (!displayName) continue;
      const entry: Entry = {
        name: displayName,
        color: r.color,
        border: r.border_color || 'transparent',
      };
      const bucket = r.variety_id
        ? plants
        : r.region_type === 'trellis'
          ? trellises
          : r.region_type === 'planting' || r.region_type === 'tree'
            ? beds
            : structures;
      if (!bucket.has(displayName)) bucket.set(displayName, entry);
    }
    const sort = (a: Entry, b: Entry) => a.name.localeCompare(b.name);
    return {
      plants: [...plants.values()].sort(sort),
      beds: [...beds.values()].sort(sort),
      trellises: [...trellises.values()].sort(sort),
      structures: [...structures.values()].sort(sort),
      total: plants.size + beds.size + trellises.size + structures.size,
    };
  }, [zoneRegions, varieties]);

  // Selection info
  const selectedRegions = useMemo(
    () => zoneRegions.filter((r) => selectedIds.has(r.id)),
    [zoneRegions, selectedIds]
  );
  const selectionSqFt = useMemo(
    () =>
      selectedRegions.reduce((sum, r) => sum + r.width * r.height * FT_PER_CELL * FT_PER_CELL, 0),
    [selectedRegions]
  );

  const isDialogOpen = !!newRect || !!editRegion;
  const dialogRegion = editRegion;

  // Re-seed color + border state whenever the dialog opens on a new subject.
  // If we're editing an existing region, honour its current colors; if we're
  // creating from a drawn rect, fall back to the palette default.
  useEffect(() => {
    if (!isDialogOpen) return;
    setSelectedColor(dialogRegion?.color ?? COLOR_PRESETS[0]);
    setSelectedBorder(dialogRegion?.border_color ?? BORDER_PRESETS[0]);
  }, [isDialogOpen, dialogRegion?.id, dialogRegion?.color, dialogRegion?.border_color, newRect]);

  const wrapperClass = fullscreen ? 'fixed inset-0 z-40 flex flex-col bg-background' : '';

  const cursorForTool: Record<Tool, string> = {
    draw: 'crosshair',
    select: isPanning ? 'grabbing' : 'default',
    pan: isPanning ? 'grabbing' : 'grab',
    eraser: 'pointer',
  };
  const canvasCursor = stampTemplate
    ? 'copy'
    : spaceHeld
      ? isPanning
        ? 'grabbing'
        : 'grab'
      : cursorForTool[activeTool];

  const tools: { id: Tool; icon: typeof Pencil; label: string; shortcut: string; hint: string }[] =
    [
      {
        id: 'select',
        icon: MousePointer2,
        label: 'Select',
        shortcut: 'V',
        hint: 'Default tool. Drag empty space to pan. Click an element to select, drag to move. Shift+click to select more. Hold Space to pan from any tool.',
      },
      {
        id: 'eraser',
        icon: Eraser,
        label: 'Eraser',
        shortcut: 'E',
        hint: 'Click an element to delete it.',
      },
    ];

  return (
    <div className={wrapperClass}>
      {/* Top bar */}
      <div
        className={`flex items-center gap-2 ${fullscreen ? 'px-4 py-2 border-b border-border/40 shrink-0' : 'mb-3'}`}
      >
        {/* Zone tabs */}
        <div className="flex items-center gap-1.5 overflow-x-auto flex-1 min-w-0">
          {zones.map((z) => (
            <button
              key={z.id}
              onClick={() => setActiveZoneId(z.id)}
              title={z.name}
              className={`text-[11px] font-medium px-2.5 py-1 rounded-full whitespace-nowrap transition-all ${
                z.id === activeZoneId
                  ? 'bg-emerald-600 text-white shadow-sm'
                  : 'bg-card text-muted-foreground ring-1 ring-border/60 hover:bg-muted/50'
              }`}
            >
              {z.name}
            </button>
          ))}
          <button
            onClick={() => setAddZoneOpen(true)}
            title="Add new zone"
            className="text-[11px] text-emerald-600 hover:text-emerald-700 px-1.5 shrink-0"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Top-right actions — unified icon pill for zone management */}
        <div className="flex items-center gap-1 shrink-0">
          {stampTemplate && (
            <div className="flex items-center gap-1.5 flex-wrap">
              <button
                onClick={() => {
                  setStampTemplate(null);
                  setStampPos(null);
                  setStampRepeat({ count: 1, spacingCells: 0, direction: 'row' });
                }}
                className="text-[10px] font-medium px-2 py-1 rounded-full bg-amber-100 text-amber-800 ring-1 ring-amber-300/60 flex items-center gap-1"
              >
                {stampTemplate.name} <X className="w-2.5 h-2.5" />
              </button>
              {/* Repeat controls */}
              <div className="flex items-center gap-1 text-[10px]">
                <label className="text-muted-foreground/60 shrink-0">Repeat</label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={stampRepeat.count}
                  onChange={(e) =>
                    setStampRepeat({
                      ...stampRepeat,
                      count: Math.max(1, parseInt(e.target.value) || 1),
                    })
                  }
                  className="w-10 h-5 text-center text-[10px] rounded ring-1 ring-border/60 bg-card px-1"
                  title="Number of copies"
                />
                {stampRepeat.count > 1 && (
                  <>
                    <label className="text-muted-foreground/60 shrink-0">gap</label>
                    <input
                      type="number"
                      min={0}
                      max={40}
                      value={(stampRepeat.spacingCells * FT_PER_CELL).toFixed(1)}
                      step={0.5}
                      onChange={(e) =>
                        setStampRepeat({
                          ...stampRepeat,
                          spacingCells: Math.round((parseFloat(e.target.value) || 0) / FT_PER_CELL),
                        })
                      }
                      className="w-12 h-5 text-center text-[10px] rounded ring-1 ring-border/60 bg-card px-1"
                      title="Gap between copies (ft)"
                    />
                    <span className="text-muted-foreground/60">ft</span>
                    <button
                      onClick={() =>
                        setStampRepeat({
                          ...stampRepeat,
                          direction: stampRepeat.direction === 'row' ? 'col' : 'row',
                        })
                      }
                      className="px-1.5 py-0.5 rounded bg-muted/60 ring-1 ring-border/40 text-muted-foreground hover:text-foreground transition-colors"
                      title="Toggle row/column direction"
                    >
                      {stampRepeat.direction === 'row' ? 'Row →' : 'Col ↓'}
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
          <div className="flex items-center gap-0.5 rounded-lg bg-muted/50 ring-1 ring-border/40 p-0.5">
            {mapMode === 'edit' && (
              <button
                onClick={() => setTemplateDialogOpen(true)}
                className="inline-flex items-center justify-center h-7 w-7 sm:w-auto sm:px-2 rounded-md text-muted-foreground hover:text-foreground hover:bg-background/50 transition-colors relative"
                title={`Templates${templates.length > 0 ? ` (${templates.length})` : ''}`}
                aria-label="Templates"
              >
                <LayoutTemplate className="w-3.5 h-3.5" />
                <span className="hidden sm:inline text-[11px] font-medium ml-1">Templates</span>
                {templates.length > 0 && (
                  <span className="absolute -top-1 -right-1 sm:static sm:ml-1 text-[9px] bg-emerald-100 text-emerald-700 rounded-full px-1.5 leading-4 font-semibold">
                    {templates.length}
                  </span>
                )}
              </button>
            )}
            <button
              onClick={() => setFullscreen(!fullscreen)}
              className="inline-flex items-center justify-center h-7 w-7 rounded-md text-muted-foreground hover:text-foreground hover:bg-background/50 transition-colors"
              title={fullscreen ? 'Exit fullscreen' : 'Fullscreen editor'}
              aria-label={fullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
            >
              {fullscreen ? (
                <Minimize2 className="w-3.5 h-3.5" />
              ) : (
                <Maximize2 className="w-3.5 h-3.5" />
              )}
            </button>
            {activeZone && mapMode === 'edit' && (
              <>
                <button
                  onClick={() => setEditZone(activeZone)}
                  title="Edit zone size & name"
                  aria-label="Edit zone"
                  className="inline-flex items-center justify-center h-7 w-7 rounded-md text-muted-foreground hover:text-emerald-600 hover:bg-emerald-50 transition-colors"
                >
                  <Settings2 className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => setZoneDeleteConfirm(activeZone)}
                  title={`Delete "${activeZone.name}" and every element in it`}
                  aria-label="Delete zone"
                  className="inline-flex items-center justify-center h-7 w-7 rounded-md text-muted-foreground/50 hover:text-terra-500 hover:bg-terra-50 transition-colors"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {!activeZone ? (
        <div className="rounded-xl bg-card shadow-sm ring-1 ring-black/[0.04] px-6 py-12 text-center">
          <p className="font-heading font-semibold text-foreground mb-1">No zones yet</p>
          <p className="text-sm text-muted-foreground">
            Create your first garden zone to start mapping.
          </p>
        </div>
      ) : (
        <>
          {/* Toolbar — wraps on narrow screens instead of crowding */}
          <div
            className={`flex items-center justify-between gap-2 flex-wrap ${fullscreen ? 'px-3 sm:px-4 py-1.5' : 'mb-2'}`}
          >
            <div className="flex items-center gap-1.5 flex-wrap">
              {/* Mode toggle — View (browse) vs Edit (mutate). Single prominent control. */}
              <div
                className="inline-flex items-center rounded-lg bg-muted/50 ring-1 ring-border/40 p-0.5"
                role="tablist"
                aria-label="Map mode"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={mapMode === 'view'}
                  onClick={() => {
                    setMapMode('view');
                    setActiveTool('select');
                    setStampTemplate(null);
                    setStampPos(null);
                    setSelectedIds(new Set());
                  }}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-all ${
                    mapMode === 'view'
                      ? 'bg-background text-foreground shadow-sm ring-1 ring-border/60'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                  title="Browse the garden — pan, zoom, tap a box to see what it is. No accidental edits."
                >
                  View
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={mapMode === 'edit'}
                  onClick={() => setMapMode('edit')}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-all ${
                    mapMode === 'edit'
                      ? 'bg-emerald-600 text-white shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                  title="Edit — add, move, merge, rotate, delete elements. Undo/redo available."
                >
                  Edit
                </button>
              </div>

              {mapMode === 'edit' && (
                <>
                  {/* Primary action: Add — drops you into Draw mode for one box */}
                  <button
                    onClick={() => {
                      setActiveTool('draw');
                      setStampTemplate(null);
                      setStampPos(null);
                      setStampRepeat({ count: 1, spacingCells: 0, direction: 'row' });
                    }}
                    className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold transition-all ${
                      activeTool === 'draw'
                        ? 'bg-emerald-700 text-white shadow-sm ring-2 ring-emerald-500/40'
                        : 'bg-emerald-600 text-white hover:bg-emerald-700 shadow-sm'
                    }`}
                    title={
                      activeTool === 'draw'
                        ? 'Drag on the map to draw a new element. Press Esc to cancel.'
                        : 'Add a new element — drag on the map to draw a box. (A)'
                    }
                    aria-label="Add new element"
                  >
                    <Plus className="w-3 h-3" />
                    <span className="hidden xs:inline">
                      {activeTool === 'draw' ? 'Drawing…' : 'Add'}
                    </span>
                    <kbd className="hidden sm:inline text-[8px] opacity-70 ml-0.5">A</kbd>
                  </button>

                  {/* Secondary tools */}
                  <div className="flex items-center gap-0.5 rounded-lg bg-muted/50 ring-1 ring-border/40 p-0.5">
                    {tools.map((t) => {
                      const Icon = t.icon;
                      const isActive = !stampTemplate && activeTool === t.id;
                      return (
                        <button
                          key={t.id}
                          onClick={() => {
                            setActiveTool(t.id);
                            setStampTemplate(null);
                            setStampPos(null);
                            setStampRepeat({ count: 1, spacingCells: 0, direction: 'row' });
                          }}
                          className={`flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-all ${
                            isActive
                              ? 'bg-background text-foreground shadow-sm ring-1 ring-border/60'
                              : 'text-muted-foreground hover:text-foreground hover:bg-background/50'
                          }`}
                          title={`${t.label} (${t.shortcut}) — ${t.hint}`}
                          aria-label={`${t.label} tool. ${t.hint}`}
                        >
                          <Icon className="w-3 h-3" />
                          <span className="hidden sm:inline">{t.label}</span>
                          <kbd className="hidden sm:inline text-[8px] text-muted-foreground/50 ml-0.5">
                            {t.shortcut}
                          </kbd>
                        </button>
                      );
                    })}
                  </div>

                  {/* Undo / Redo */}
                  <div className="flex items-center gap-0.5 rounded-lg bg-muted/50 ring-1 ring-border/40 p-0.5">
                    <button
                      onClick={undo}
                      disabled={undoStack.length === 0 || saving}
                      className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-background/50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                      title="Undo (⌘Z / Ctrl+Z)"
                      aria-label="Undo"
                    >
                      <Undo2 className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={redo}
                      disabled={redoStack.length === 0 || saving}
                      className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-background/50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                      title="Redo (⌘⇧Z / Ctrl+Y)"
                      aria-label="Redo"
                    >
                      <Redo2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </>
              )}
            </div>

            {/* Zoom controls */}
            <div className="flex items-center gap-0.5 rounded-lg bg-muted/50 ring-1 ring-border/40 p-0.5">
              <button
                onClick={() => zoomCentered(-ZOOM_STEP)}
                className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-background/50 transition-colors"
                title="Zoom out (-)"
              >
                <ZoomOut className="w-3.5 h-3.5" />
              </button>
              <span className="text-[10px] font-medium text-muted-foreground tabular-nums w-9 text-center select-none">
                {Math.round((zoom * 100) / (fitZoomBase || 1))}%
              </span>
              <button
                onClick={() => zoomCentered(ZOOM_STEP)}
                className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-background/50 transition-colors"
                title="Zoom in (+)"
              >
                <ZoomIn className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={centerOnContent}
                className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-background/50 transition-colors"
                title="Center on content"
                aria-label="Center on content"
              >
                <Locate className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={resetZoom}
                className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-background/50 transition-colors"
                title="Fit full grid (0)"
              >
                <RotateCcw className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Zone info — size + element count on the left, tool hint on the right.
              Hint truncates on narrow screens so the dimensions never get pushed off. */}
          <div
            className={`flex items-center justify-between gap-3 ${fullscreen ? 'px-3 sm:px-4 py-0.5 text-[10px]' : 'mb-1.5 text-[10px]'} text-muted-foreground/60`}
          >
            <span className="tabular-nums shrink-0">
              {(zoneCols * FT_PER_CELL).toFixed(0)} × {(zoneRows * FT_PER_CELL).toFixed(0)} ft
              <span className="mx-1.5 opacity-40">·</span>
              {zoneRegions.length} {zoneRegions.length === 1 ? 'element' : 'elements'}
            </span>
            <span className="truncate min-w-0 text-right">
              {stampTemplate
                ? 'Tap to place'
                : spaceHeld
                  ? 'Space · drag to pan'
                  : mapMode === 'view'
                    ? 'Tap a plant to open its page'
                    : activeTool === 'draw'
                      ? 'Drag to draw · Esc to cancel'
                      : activeTool === 'select'
                        ? 'Drag empty to pan · Tap to select'
                        : activeTool === 'pan'
                          ? 'Drag to pan'
                          : 'Tap an element to delete'}
            </span>
          </div>

          {/* Canvas */}
          <div
            ref={containerRef}
            className={`${fullscreen ? 'flex-1 min-h-0' : 'rounded-xl ring-1 ring-black/[0.08]'} overflow-hidden bg-parchment-100 relative`}
            style={{
              // dvh, not vh: on mobile the browser chrome overlaps 100vh, which
              // used to push the bottom of the map (and its legend) off-screen.
              ...(fullscreen ? {} : { maxHeight: '60dvh' }),
              touchAction: 'none',
            }}
          >
            <canvas
              ref={canvasRef}
              role="img"
              aria-label={`Garden map of ${activeZone?.name ?? 'this zone'}: ${zoneRegions.length} element${
                zoneRegions.length === 1 ? '' : 's'
              }. Plant list available in the legend below.`}
              style={{
                cursor: canvasCursor,
                transform: `translate(${panOffset.x}px, ${panOffset.y}px)`,
                transformOrigin: '0 0',
                willChange: 'transform',
              }}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={handlePointerCancel}
            />
            {/* Floating legend (fullscreen only) */}
            {fullscreen && legend.total > 0 && (
              <details className="group/fslegend absolute bottom-3 right-3 z-10 rounded-xl bg-card/95 ring-1 ring-black/[0.08] shadow-lg backdrop-blur-sm max-w-[45%] max-h-[50%] overflow-hidden flex flex-col">
                <summary className="flex items-center justify-between gap-2 px-3 py-2 cursor-pointer list-none [&::-webkit-details-marker]:hidden select-none hover:bg-muted/40">
                  <span className="text-[10px] font-semibold tracking-[0.18em] uppercase text-foreground/70">
                    Legend
                    <span className="ml-1.5 text-muted-foreground/60 font-normal tracking-normal normal-case">
                      {legend.total}
                    </span>
                  </span>
                  <ChevronDown className="w-3.5 h-3.5 text-muted-foreground/50 transition-transform group-open/fslegend:rotate-180" />
                </summary>
                <div className="px-3 pb-2.5 pt-1 overflow-y-auto space-y-2">
                  {[
                    { title: 'Plants', items: legend.plants },
                    { title: 'Beds', items: legend.beds },
                    { title: 'Trellises', items: legend.trellises },
                    { title: 'Structures', items: legend.structures },
                  ]
                    .filter((g) => g.items.length > 0)
                    .map((g) => (
                      <div key={g.title}>
                        <p className="text-[9px] font-semibold tracking-[0.18em] uppercase text-foreground/50 mb-1">
                          {g.title}
                        </p>
                        <div className="flex flex-col gap-1">
                          {g.items.map((item) => (
                            <div key={item.name} className="flex items-center gap-1.5 text-[11px]">
                              <div
                                className="w-3 h-3 rounded-sm shrink-0"
                                style={{
                                  backgroundColor: item.color,
                                  border: `1.5px solid ${item.border}`,
                                  opacity: 0.82,
                                }}
                              />
                              <span className="text-foreground/70 truncate">{item.name}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                </div>
              </details>
            )}
          </div>

          {/* Selection info bar — stacks on mobile (info row + action row),
              goes inline on sm+. Buttons are icon-only on mobile and grow
              labels on sm+ so the bar never wraps or gets crowded. */}
          {selectedIds.size > 0 && (
            <div
              className={`flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-3 ${fullscreen ? 'px-3 sm:px-4 py-2 border-t border-border/40 shrink-0 bg-card/60 backdrop-blur-sm' : 'mt-2'}`}
            >
              {/* Info */}
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <span className="inline-flex items-center gap-1 rounded-md bg-blue-50 ring-1 ring-blue-200/60 px-2 py-1 text-[11px] font-semibold text-blue-800 shrink-0 tabular-nums">
                  <Square className="w-2.5 h-2.5" />
                  {selectedIds.size}
                </span>
                <span className="text-[11px] text-foreground font-medium tabular-nums shrink-0">
                  {selectionSqFt < 1
                    ? `${(selectionSqFt * 144).toFixed(0)} sq in`
                    : `${selectionSqFt.toFixed(1)} sq ft`}
                  {selectedRegions.length === 1 && (
                    <span className="hidden sm:inline text-muted-foreground/70 ml-1 font-normal">
                      ({(selectedRegions[0].width * FT_PER_CELL).toFixed(1)}&apos; ×{' '}
                      {(selectedRegions[0].height * FT_PER_CELL).toFixed(1)}&apos;)
                    </span>
                  )}
                </span>
                {selectedRegions.length === 1 && (
                  <span className="text-[11px] text-muted-foreground truncate min-w-0">
                    {selectedRegions[0].name}
                  </span>
                )}
                {selectedRegions.length === 1 &&
                  selectedRegions[0].variety_id &&
                  (() => {
                    const v = varieties.find((v) => v.id === selectedRegions[0].variety_id);
                    if (!v) return null;
                    const c = crops.find((c) => c.id === v.crop_id);
                    return c ? (
                      <Link
                        href={`/crops/${c.id}`}
                        className="hidden sm:inline-flex items-center gap-1 text-[11px] text-emerald-600 font-medium hover:text-emerald-700 rounded-md bg-emerald-50 ring-1 ring-emerald-200/60 px-1.5 py-0.5 shrink-0"
                      >
                        {v.name}
                        <ExternalLink className="w-2.5 h-2.5" />
                      </Link>
                    ) : null;
                  })()}
              </div>
              {/* Actions — icon-only on mobile, icon+label on sm+ */}
              {mapMode === 'edit' && (
                <div className="flex items-center gap-1 shrink-0 flex-wrap sm:flex-nowrap">
                  {selectedIds.size >= 2 && (
                    <button
                      onClick={mergeSelected}
                      disabled={saving}
                      className="inline-flex items-center justify-center gap-1 h-8 w-8 sm:w-auto sm:px-2.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 transition-colors"
                      title="Combine selected into one irregular shape"
                      aria-label="Merge"
                    >
                      <Merge className="w-3.5 h-3.5" />
                      <span className="hidden sm:inline text-[11px] font-medium">Merge</span>
                    </button>
                  )}
                  <button
                    onClick={rotateSelected}
                    disabled={saving}
                    className="inline-flex items-center justify-center gap-1 h-8 w-8 sm:w-auto sm:px-2.5 rounded-lg ring-1 ring-border/60 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 transition-colors"
                    title="Rotate selected 90° clockwise"
                    aria-label="Rotate 90°"
                  >
                    <RotateCw className="w-3.5 h-3.5" />
                    <span className="hidden sm:inline text-[11px] font-medium">Rotate</span>
                  </button>
                  <button
                    onClick={() => {
                      const selected = zoneRegions.filter((r) => selectedIds.has(r.id));
                      if (selected.length > 0) duplicateRegions(selected);
                    }}
                    disabled={saving}
                    className="inline-flex items-center justify-center gap-1 h-8 w-8 sm:w-auto sm:px-2.5 rounded-lg ring-1 ring-border/60 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 transition-colors"
                    title="Duplicate selected"
                    aria-label="Duplicate"
                  >
                    <Copy className="w-3.5 h-3.5" />
                    <span className="hidden sm:inline text-[11px] font-medium">Duplicate</span>
                  </button>
                  <button
                    onClick={() => {
                      if (selectedIds.size === 1) {
                        const reg = zoneRegions.find((r) => r.id === [...selectedIds][0]);
                        if (reg) setEditRegion(reg);
                      }
                    }}
                    disabled={selectedIds.size !== 1}
                    className="inline-flex items-center justify-center gap-1 h-8 w-8 sm:w-auto sm:px-2.5 rounded-lg ring-1 ring-border/60 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 transition-colors"
                    title="Edit selected element"
                    aria-label="Edit"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                    <span className="hidden sm:inline text-[11px] font-medium">Edit</span>
                  </button>
                  <div className="w-px h-5 bg-border/40 mx-0.5" />
                  <button
                    onClick={() => setSelectedIds(new Set())}
                    className="inline-flex items-center justify-center h-8 w-8 rounded-lg text-muted-foreground/60 hover:text-foreground hover:bg-muted transition-colors"
                    title="Clear selection"
                    aria-label="Clear selection"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
              {mapMode === 'view' && (
                <button
                  onClick={() => setSelectedIds(new Set())}
                  className="inline-flex items-center justify-center h-8 w-8 rounded-lg text-muted-foreground/60 hover:text-foreground hover:bg-muted transition-colors self-end sm:self-auto"
                  title="Clear selection"
                  aria-label="Clear selection"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          )}

          {/* Legend */}
          {legend.total > 0 && !fullscreen && (
            <details open className="group/section mt-3">
              <summary className="flex items-center justify-between mb-2 cursor-pointer list-none [&::-webkit-details-marker]:hidden select-none">
                <h2 className="text-[11px] font-semibold tracking-[0.18em] uppercase text-foreground/70">
                  Legend
                  <span className="ml-1.5 text-muted-foreground/60 font-normal tracking-normal normal-case">
                    {legend.total}
                  </span>
                </h2>
                <ChevronDown className="w-4 h-4 text-muted-foreground/40 transition-transform group-open/section:rotate-180" />
              </summary>
              <div className="space-y-2.5">
                {[
                  { title: 'Plants', items: legend.plants },
                  { title: 'Trellises', items: legend.trellises },
                  { title: 'Structures', items: legend.structures },
                ]
                  .filter((g) => g.items.length > 0)
                  .map((g) => (
                    <div key={g.title}>
                      <p className="text-[10px] font-medium tracking-[0.18em] uppercase text-muted-foreground/50 mb-1">
                        {g.title}
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {g.items.map((item) => (
                          <div key={item.name} className="flex items-center gap-1.5 text-[11px]">
                            <div
                              className="w-3 h-3 rounded-sm"
                              style={{
                                backgroundColor: item.color,
                                borderColor: item.border,
                                borderWidth: 1.5,
                                borderStyle: 'solid',
                                opacity: 0.82,
                              }}
                            />
                            <span className="text-foreground/70">{item.name}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
              </div>
            </details>
          )}
        </>
      )}

      {/* Region create/edit dialog — key forces remount to avoid uncontrolled defaultValue warnings */}
      <Dialog
        key={dialogRegion?.id ?? (newRect ? 'new' : 'closed')}
        open={isDialogOpen}
        onOpenChange={(open) => {
          if (!open) {
            setNewRect(null);
            setEditRegion(null);
          }
        }}
      >
        <DialogContent className="rounded-xl sm:max-w-sm">
          <DialogHeader>
            <p className="text-xs font-medium tracking-widest uppercase text-muted-foreground/60">
              {dialogRegion ? 'Edit Element' : 'New Element'}
            </p>
            <DialogTitle className="text-xl font-heading font-semibold tracking-tight">
              {dialogRegion?.name ?? 'Define Area'}
            </DialogTitle>
            {newRect && (
              <p className="text-[10px] text-muted-foreground/50">
                {(newRect.w * FT_PER_CELL).toFixed(1)}ft × {(newRect.h * FT_PER_CELL).toFixed(1)}ft
              </p>
            )}
          </DialogHeader>
          <form onSubmit={saveRegion} className="space-y-3 mt-1">
            <div className="space-y-1.5">
              <Label htmlFor="r-name" className="text-xs font-medium text-muted-foreground">
                Name
              </Label>
              <Input
                id="r-name"
                name="name"
                required
                defaultValue={dialogRegion?.name ?? ''}
                placeholder="e.g., Tomato Bed"
                className="rounded-lg"
              />
            </div>
            <RegionTypeAndVarietyPicker
              dialogRegion={dialogRegion}
              crops={crops}
              varieties={varieties}
              typeSelection={typeSelection}
              setTypeSelection={setTypeSelection}
              onCropPicked={(cropId) => {
                const { fill, border } = colorsForCrop(cropId);
                setSelectedColor(fill);
                setSelectedBorder(border);
              }}
              onTypePicked={(type) => {
                // Trellises look like cattle panel — always gray by default.
                if (type === 'trellis') {
                  setSelectedColor('#cfd2d0');
                  setSelectedBorder('#6b6e6b');
                }
              }}
            />
            {/* Size fields (edit mode only) */}
            {dialogRegion && (
              <div className="flex gap-3">
                <div className="flex-1 space-y-1.5">
                  <Label htmlFor="r-width" className="text-xs font-medium text-muted-foreground">
                    Width (ft)
                  </Label>
                  <Input
                    id="r-width"
                    name="width_ft"
                    type="number"
                    step={0.5}
                    min={0.5}
                    defaultValue={(dialogRegion.width * FT_PER_CELL).toFixed(1)}
                    className="rounded-lg"
                  />
                </div>
                <div className="flex-1 space-y-1.5">
                  <Label htmlFor="r-height" className="text-xs font-medium text-muted-foreground">
                    Height (ft)
                  </Label>
                  <Input
                    id="r-height"
                    name="height_ft"
                    type="number"
                    step={0.5}
                    min={0.5}
                    defaultValue={(dialogRegion.height * FT_PER_CELL).toFixed(1)}
                    className="rounded-lg"
                  />
                </div>
                <div className="flex items-end pb-0.5">
                  <span className="text-[10px] text-muted-foreground/50">
                    {(dialogRegion.width * dialogRegion.height * FT_PER_CELL * FT_PER_CELL).toFixed(
                      1
                    )}{' '}
                    sq ft
                  </span>
                </div>
              </div>
            )}
            <div className="space-y-1.5">
              {/* Link to crop page if variety is assigned */}
              {dialogRegion?.variety_id &&
                (() => {
                  const v = varieties.find((v) => v.id === dialogRegion.variety_id);
                  if (!v) return null;
                  const c = crops.find((c) => c.id === v.crop_id);
                  return c ? (
                    <Link
                      href={`/crops/${c.id}`}
                      className="inline-flex items-center gap-1 text-[11px] text-emerald-600 font-medium hover:text-emerald-700 mt-1"
                    >
                      View {c.name} — {v.name}
                      <ExternalLink className="w-2.5 h-2.5" />
                    </Link>
                  ) : null;
                })()}
            </div>
            <div className="flex gap-3">
              <div className="flex-1 space-y-1.5">
                <Label className="text-xs font-medium text-muted-foreground">Fill</Label>
                <div className="flex flex-wrap gap-1">
                  {COLOR_PRESETS.map((c) => (
                    <label key={c} className="cursor-pointer">
                      <input
                        type="radio"
                        name="color"
                        value={c}
                        checked={selectedColor === c}
                        onChange={() => setSelectedColor(c)}
                        className="sr-only peer"
                      />
                      <div
                        className="w-5 h-5 rounded peer-checked:ring-2 peer-checked:ring-emerald-500 peer-checked:scale-110 transition-all"
                        style={{ backgroundColor: c }}
                      />
                    </label>
                  ))}
                </div>
              </div>
              <div className="flex-1 space-y-1.5">
                <Label className="text-xs font-medium text-muted-foreground">Border</Label>
                <div className="flex flex-wrap gap-1">
                  {BORDER_PRESETS.map((c) => (
                    <label key={c} className="cursor-pointer">
                      <input
                        type="radio"
                        name="border_color"
                        value={c}
                        checked={selectedBorder === c}
                        onChange={() => setSelectedBorder(c)}
                        className="sr-only peer"
                      />
                      <div
                        className="w-5 h-5 rounded peer-checked:ring-2 peer-checked:ring-emerald-500 peer-checked:scale-110 transition-all"
                        style={{ backgroundColor: c }}
                      />
                    </label>
                  ))}
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={() => {
                const nameInput = document.getElementById('r-name') as HTMLInputElement | null;
                if (typeSelection.startsWith('crop:')) {
                  const cropId = parseInt(typeSelection.slice(5));
                  const c = crops.find((cc) => cc.id === cropId);
                  if (c && nameInput) nameInput.value = c.name;
                  const { fill, border } = colorsForCrop(cropId);
                  setSelectedColor(fill);
                  setSelectedBorder(border);
                } else if (typeSelection === 'trellis') {
                  setSelectedColor('#cfd2d0');
                  setSelectedBorder('#6b6e6b');
                  if (nameInput) nameInput.value = 'Trellis';
                } else {
                  setSelectedColor(COLOR_PRESETS[0]);
                  setSelectedBorder(BORDER_PRESETS[0]);
                }
              }}
              className="self-start inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-emerald-700 px-2 py-1 rounded-md ring-1 ring-border/40 hover:ring-emerald-300 hover:bg-emerald-50/40 transition-colors"
              title={
                typeSelection.startsWith('crop:')
                  ? 'Reset name and colors to the defaults for this crop'
                  : typeSelection === 'trellis'
                    ? 'Reset colors to cattle-panel gray'
                    : 'Reset colors to palette default'
              }
            >
              <RotateCcw className="w-3 h-3" />
              Reset to defaults
            </button>
            {/* Edit-only actions row */}
            {dialogRegion && (
              <div className="flex items-center gap-px rounded-lg ring-1 ring-border/40 overflow-hidden">
                <button
                  type="button"
                  onClick={() => {
                    bringToFront(dialogRegion.id);
                    setEditRegion(null);
                  }}
                  className="px-3 py-1.5 text-[11px] font-medium text-muted-foreground hover:bg-muted/80 transition-colors"
                  title="Move to front (top layer)"
                >
                  Bring Front
                </button>
                <div className="w-px h-5 bg-border/40" />
                <button
                  type="button"
                  onClick={() => {
                    sendToBack(dialogRegion.id);
                    setEditRegion(null);
                  }}
                  className="px-3 py-1.5 text-[11px] font-medium text-muted-foreground hover:bg-muted/80 transition-colors"
                  title="Move to back (bottom layer)"
                >
                  Send Back
                </button>
                <div className="w-px h-5 bg-border/40" />
                <button
                  type="button"
                  onClick={() => saveAsTemplate(dialogRegion)}
                  disabled={saving}
                  className="px-3 py-1.5 text-[11px] font-medium text-emerald-600 hover:bg-emerald-50/80 transition-colors disabled:opacity-50"
                  title="Save as reusable template"
                >
                  {saving ? '...' : 'Save as Template'}
                </button>
              </div>
            )}
            <DialogFooter>
              {dialogRegion && (
                <button
                  type="button"
                  onClick={() => {
                    setEditRegion(null);
                    setDeleteConfirm(dialogRegion.id);
                  }}
                  className="rounded-lg px-4 py-2 text-sm font-medium text-terra-600 ring-1 ring-terra-200 hover:bg-terra-50 transition-colors mr-auto"
                  title="Delete this element"
                >
                  <Trash2 className="w-3.5 h-3.5 inline -mt-0.5 mr-1" />
                  Delete
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  setNewRect(null);
                  setEditRegion(null);
                }}
                className="rounded-lg px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-muted transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving}
                className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:opacity-50 transition-colors"
              >
                {saving ? 'Saving...' : dialogRegion ? 'Update' : 'Create'}
              </button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Templates dialog */}
      <Dialog open={templateDialogOpen} onOpenChange={setTemplateDialogOpen}>
        <DialogContent className="rounded-xl sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-xl font-heading font-semibold tracking-tight">
              Templates
            </DialogTitle>
            <p className="text-xs text-muted-foreground/60">
              Click a template to stamp it onto the map. Create templates by editing any element and
              choosing &quot;Save as Template.&quot;
            </p>
          </DialogHeader>
          <div className="space-y-1 max-h-[50vh] overflow-y-auto">
            {templates.map((t) => (
              <div
                key={t.id}
                className="flex items-center rounded-lg hover:bg-muted/50 transition-colors"
              >
                <button
                  onClick={() => {
                    setStampTemplate(t);
                    setTemplateDialogOpen(false);
                  }}
                  className="flex-1 flex items-center gap-3 px-3 py-2.5 text-left min-w-0"
                >
                  <div
                    className={`w-8 h-6 shrink-0 ${t.element_type === 'tree' ? 'rounded-full' : 'rounded-sm'}`}
                    style={{
                      backgroundColor: t.color,
                      border: `1.5px solid ${t.border_color}`,
                      opacity: 0.82,
                    }}
                  />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium block truncate">{t.name}</span>
                    <span className="text-[10px] text-muted-foreground/50">
                      {(t.width * FT_PER_CELL).toFixed(1)}&apos; ×{' '}
                      {(t.height * FT_PER_CELL).toFixed(1)}&apos; ·{' '}
                      {(t.width * t.height * FT_PER_CELL * FT_PER_CELL).toFixed(1)} sq ft
                    </span>
                  </div>
                </button>
                <button
                  onClick={() => {
                    setEditTemplate(t);
                    setTemplateDialogOpen(false);
                  }}
                  className="p-2 text-muted-foreground/50 hover:text-emerald-600 hover:bg-emerald-50 rounded-md transition-colors shrink-0"
                  title="Edit this template"
                  aria-label="Edit template"
                >
                  <Pencil className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => setTemplateDeleteConfirm(t)}
                  className="p-2 text-muted-foreground/50 hover:text-terra-600 hover:bg-terra-50 rounded-md transition-colors shrink-0 mr-1"
                  title="Delete this template"
                  aria-label="Delete template"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
            {templates.length === 0 && (
              <div className="py-8 text-center space-y-2">
                <LayoutTemplate className="w-8 h-8 text-muted-foreground/30 mx-auto" />
                <p className="text-sm text-muted-foreground/60">No templates yet</p>
                <p className="text-xs text-muted-foreground/40">
                  Draw an element, then click &quot;Save as Template&quot; in its edit dialog to
                  create one.
                </p>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <ConfirmDialog
        open={deleteConfirm !== null}
        onOpenChange={() => setDeleteConfirm(null)}
        title="Delete element?"
        description="This will be permanently removed from the map."
        onConfirm={() => deleteConfirm && deleteRegion(deleteConfirm)}
      />

      {/* Edit template dialog */}
      <FormDialog
        open={editTemplate !== null}
        onOpenChange={(o) => {
          if (!o) setEditTemplate(null);
        }}
        title="Edit Template"
      >
        {editTemplate && (
          <form onSubmit={updateTemplate} className="space-y-3 mt-1">
            <div className="space-y-1.5">
              <Label htmlFor="t-name" className="text-xs font-medium text-muted-foreground">
                Name
              </Label>
              <Input id="t-name" name="name" defaultValue={editTemplate.name} required autoFocus />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="t-type" className="text-xs font-medium text-muted-foreground">
                Element type
              </Label>
              <select
                id="t-type"
                name="element_type"
                defaultValue={editTemplate.element_type}
                className="w-full h-10 rounded-lg ring-1 ring-border/60 bg-card px-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
              >
                {['bed', 'tree', 'bush', 'trellis', 'cage', 'structure', 'custom'].map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1.5">
                <Label htmlFor="t-width" className="text-xs font-medium text-muted-foreground">
                  Width (ft)
                </Label>
                <Input
                  id="t-width"
                  name="width"
                  type="number"
                  step="0.5"
                  min="0.5"
                  defaultValue={(editTemplate.width * FT_PER_CELL).toString()}
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="t-height" className="text-xs font-medium text-muted-foreground">
                  Height (ft)
                </Label>
                <Input
                  id="t-height"
                  name="height"
                  type="number"
                  step="0.5"
                  min="0.5"
                  defaultValue={(editTemplate.height * FT_PER_CELL).toString()}
                  required
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-muted-foreground">Fill color</Label>
              <div className="flex flex-wrap gap-1.5">
                {COLOR_PRESETS.map((c, i) => (
                  <label key={c} className="cursor-pointer">
                    <input
                      type="radio"
                      name="color"
                      value={c}
                      defaultChecked={c === editTemplate.color}
                      className="sr-only peer"
                    />
                    <span
                      className="block w-7 h-7 rounded-md ring-1 ring-border/60 peer-checked:ring-2 peer-checked:ring-emerald-500 transition-all"
                      style={{ backgroundColor: c, opacity: 0.82 }}
                      title={BORDER_PRESETS[i]}
                    />
                  </label>
                ))}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-muted-foreground">Border color</Label>
              <div className="flex flex-wrap gap-1.5">
                {BORDER_PRESETS.map((c) => (
                  <label key={c} className="cursor-pointer">
                    <input
                      type="radio"
                      name="border_color"
                      value={c}
                      defaultChecked={c === editTemplate.border_color}
                      className="sr-only peer"
                    />
                    <span
                      className="block w-7 h-7 rounded-md ring-1 ring-border/60 peer-checked:ring-2 peer-checked:ring-emerald-500 transition-all"
                      style={{ backgroundColor: c }}
                    />
                  </label>
                ))}
              </div>
            </div>
            <DialogFooter className="flex gap-2 pt-2">
              <button
                type="button"
                onClick={() => setEditTemplate(null)}
                className="flex-1 rounded-lg py-2 text-sm font-medium ring-1 ring-border hover:bg-muted transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving}
                className="flex-1 rounded-lg bg-emerald-600 text-white py-2 text-sm font-medium hover:bg-emerald-700 disabled:opacity-50 transition-colors"
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
            </DialogFooter>
          </form>
        )}
      </FormDialog>

      {/* Delete template confirmation */}
      <ConfirmDialog
        open={templateDeleteConfirm !== null}
        onOpenChange={() => setTemplateDeleteConfirm(null)}
        title={`Delete "${templateDeleteConfirm?.name ?? 'template'}"?`}
        description="Map elements already placed from this template will remain. The template itself will be removed."
        onConfirm={() => templateDeleteConfirm && deleteTemplate(templateDeleteConfirm.id)}
      />

      {/* Delete zone (map) confirmation */}
      <ConfirmDialog
        open={zoneDeleteConfirm !== null}
        onOpenChange={() => setZoneDeleteConfirm(null)}
        title={`Delete map "${zoneDeleteConfirm?.name ?? 'zone'}"?`}
        description="This permanently removes the map and every element on it. This cannot be undone."
        onConfirm={() => {
          if (zoneDeleteConfirm) deleteZone(zoneDeleteConfirm.id);
          setZoneDeleteConfirm(null);
        }}
      />

      {/* Add Zone dialog */}
      <FormDialog open={addZoneOpen} onOpenChange={setAddZoneOpen} title="New Garden Zone">
        <form onSubmit={addZone} className="space-y-3 mt-1">
          <div className="space-y-1.5">
            <Label htmlFor="z-name" className="text-xs font-medium text-muted-foreground">
              Name
            </Label>
            <Input id="z-name" name="name" required defaultValue="Garden" className="rounded-lg" />
          </div>
          <div className="flex gap-3">
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="z-w" className="text-xs font-medium text-muted-foreground">
                Width (ft)
              </Label>
              <Input
                id="z-w"
                name="width_ft"
                type="number"
                defaultValue={50}
                step={0.5}
                className="rounded-lg"
              />
            </div>
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="z-h" className="text-xs font-medium text-muted-foreground">
                Height (ft)
              </Label>
              <Input
                id="z-h"
                name="height_ft"
                type="number"
                defaultValue={50}
                step={0.5}
                className="rounded-lg"
              />
            </div>
          </div>
          <DialogFooter>
            <button
              type="button"
              onClick={() => setAddZoneOpen(false)}
              className="rounded-lg px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-muted"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:opacity-50"
            >
              {saving ? 'Creating...' : 'Create Zone'}
            </button>
          </DialogFooter>
        </form>
      </FormDialog>

      {/* Edit Zone dialog */}
      <FormDialog
        open={editZone !== null}
        onOpenChange={(o) => {
          if (!o) setEditZone(null);
        }}
        title="Edit Garden Zone"
      >
        {editZone && (
          <form onSubmit={saveZoneEdit} className="space-y-3 mt-1" key={editZone.id}>
            <div className="space-y-1.5">
              <Label htmlFor="ez-name" className="text-xs font-medium text-muted-foreground">
                Name
              </Label>
              <Input
                id="ez-name"
                name="name"
                required
                defaultValue={editZone.name}
                className="rounded-lg"
              />
            </div>
            <div className="flex gap-3">
              <div className="flex-1 space-y-1.5">
                <Label htmlFor="ez-w" className="text-xs font-medium text-muted-foreground">
                  Width (ft)
                </Label>
                <Input
                  id="ez-w"
                  name="width_ft"
                  type="number"
                  defaultValue={(editZone.cols * FT_PER_CELL).toString()}
                  step={0.5}
                  min={0.5}
                  required
                  className="rounded-lg"
                />
              </div>
              <div className="flex-1 space-y-1.5">
                <Label htmlFor="ez-h" className="text-xs font-medium text-muted-foreground">
                  Height (ft)
                </Label>
                <Input
                  id="ez-h"
                  name="height_ft"
                  type="number"
                  defaultValue={(editZone.rows * FT_PER_CELL).toString()}
                  step={0.5}
                  min={0.5}
                  required
                  className="rounded-lg"
                />
              </div>
            </div>
            <p className="text-[10px] text-muted-foreground/60 leading-snug">
              Shrinking below existing elements&apos; extents will not delete them, but they may sit
              outside the visible grid until you move or resize them.
            </p>
            <DialogFooter>
              <button
                type="button"
                onClick={() => setEditZone(null)}
                className="rounded-lg px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-muted"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving}
                className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
            </DialogFooter>
          </form>
        )}
      </FormDialog>
    </div>
  );
}

// Controlled Type + Variety pickers. The variety dropdown only shows varieties
// that belong to the crop selected in the Type picker, so you don't scroll past
// every variety of every other crop to find "Gala" inside "Apple".
function RegionTypeAndVarietyPicker({
  dialogRegion,
  crops,
  varieties,
  typeSelection,
  setTypeSelection,
  onCropPicked,
  onTypePicked,
}: {
  dialogRegion: GardenRegion | null;
  crops: Crop[];
  varieties: Variety[];
  typeSelection: string;
  setTypeSelection: (v: string) => void;
  onCropPicked?: (cropId: number) => void;
  onTypePicked?: (type: string) => void;
}) {
  // Initial value — derived once when the picker mounts (the Dialog is keyed on
  // the subject, so this component remounts when the edited region changes).
  const initialType = useMemo(() => {
    const vid = dialogRegion?.variety_id;
    if (vid) {
      const v = varieties.find((vv) => vv.id === vid);
      if (v) return `crop:${v.crop_id}`;
    }
    return dialogRegion?.region_type ?? 'planting';
  }, [dialogRegion, varieties]);

  useEffect(() => {
    setTypeSelection(initialType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialType]);

  const isCropSelection = typeSelection.startsWith('crop:');
  const selectedCropId = isCropSelection ? parseInt(typeSelection.slice(5)) : null;
  const filteredVarieties = useMemo(
    () =>
      selectedCropId == null
        ? []
        : varieties
            .filter((v) => v.crop_id === selectedCropId)
            .sort((a, b) => a.name.localeCompare(b.name)),
    [selectedCropId, varieties]
  );

  return (
    <>
      <div className="space-y-1.5">
        <Label htmlFor="r-type" className="text-xs font-medium text-muted-foreground">
          What is this?
        </Label>
        <select
          name="region_type"
          id="r-type"
          value={typeSelection}
          onChange={(e) => {
            setTypeSelection(e.target.value);
            const v = e.target.value;
            if (v.startsWith('crop:')) {
              const cropId = parseInt(v.slice(5));
              const c = crops.find((cc) => cc.id === cropId);
              // Auto-populate empty name with the crop name
              const nameInput = document.getElementById('r-name') as HTMLInputElement | null;
              if (c && nameInput && !nameInput.value) nameInput.value = c.name;
              // Auto-pick stable crop-specific colors
              if (c) onCropPicked?.(cropId);
            } else {
              onTypePicked?.(v);
            }
          }}
          className="w-full rounded-lg border px-3 py-2 text-sm bg-background ring-1 ring-black/[0.04]"
        >
          <optgroup label="Plants">
            {crops
              .slice()
              .sort((a, b) => a.name.localeCompare(b.name))
              .map((c) => (
                <option key={`crop-${c.id}`} value={`crop:${c.id}`}>
                  {c.name}
                </option>
              ))}
          </optgroup>
          <optgroup label="Beds">
            <option value="planting">Planting Bed</option>
            <option value="tree">Tree / Bush</option>
          </optgroup>
          <optgroup label="Structures">
            <option value="trellis">Trellis</option>
            <option value="path">Path</option>
            <option value="structure">Structure</option>
            <option value="landmark">Landmark</option>
          </optgroup>
        </select>
      </div>

      {/* Variety picker — only when a crop is selected AND that crop has varieties */}
      {isCropSelection && filteredVarieties.length > 0 && (
        <div className="space-y-1.5">
          <Label htmlFor="r-variety" className="text-xs font-medium text-muted-foreground">
            Variety (optional)
          </Label>
          <select
            name="variety_id"
            id="r-variety"
            defaultValue={
              dialogRegion?.variety_id &&
              filteredVarieties.some((v) => v.id === dialogRegion.variety_id)
                ? dialogRegion.variety_id.toString()
                : ''
            }
            onChange={(e) => {
              // Autofill name with the variety name if empty
              const nameInput = document.getElementById('r-name') as HTMLInputElement | null;
              if (!nameInput || nameInput.value) return;
              const vid = parseInt(e.target.value);
              const v = varieties.find((vv) => vv.id === vid);
              if (v) nameInput.value = v.name;
            }}
            className="w-full rounded-lg border px-3 py-2 text-sm bg-background ring-1 ring-black/[0.04]"
          >
            <option value="">No specific variety</option>
            {filteredVarieties.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Hidden field to always submit variety_id in the form, empty if not applicable */}
      {!(isCropSelection && filteredVarieties.length > 0) && (
        <input type="hidden" name="variety_id" value="" />
      )}
    </>
  );
}
