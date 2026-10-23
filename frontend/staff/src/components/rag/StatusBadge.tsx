import type { JobStatus, ResourceStateStatus } from '../../lib/ragTypes';
import { Badge, type BadgeVariant } from '../ui/badge';

const VARIANTS: Record<ResourceStateStatus | JobStatus, BadgeVariant> = {
  NEVER: 'outline',
  QUEUED: 'info',
  RUNNING: 'info',
  READY: 'success',
  SUCCEEDED: 'success',
  FAILED: 'danger',
};

export function StatusBadge({
  status,
  children,
  title,
}: {
  status: ResourceStateStatus | JobStatus;
  children?: React.ReactNode;
  title?: string;
}) {
  return (
    <Badge variant={VARIANTS[status]} title={title}>
      {children ?? status}
    </Badge>
  );
}

export function isActive(status: ResourceStateStatus | JobStatus): boolean {
  return status === 'QUEUED' || status === 'RUNNING';
}
