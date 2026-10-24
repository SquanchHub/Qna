import { cn } from '../../lib/utils';

export type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'outline';

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

export function Badge({ className, variant = 'default', ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium',
        variant === 'default' && 'bg-indigo-600/20 text-indigo-300',
        variant === 'success' && 'bg-emerald-600/20 text-emerald-300',
        variant === 'warning' && 'bg-amber-600/20 text-amber-300',
        variant === 'danger' && 'bg-red-600/20 text-red-300',
        variant === 'info' && 'bg-sky-600/20 text-sky-300',
        variant === 'outline' && 'border border-slate-600 text-slate-300',
        className
      )}
      {...props}
    />
  );
}
