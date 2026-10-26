import { cn } from '../../lib/utils';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'outline' | 'ghost' | 'destructive';
  size?: 'sm' | 'md' | 'lg';
}

export function Button({ className, variant = 'default', size = 'md', ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center rounded-lg font-semibold transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-surface',
        'disabled:opacity-50 disabled:pointer-events-none',
        variant === 'default' && 'bg-accent text-accent-contrast hover:bg-accent/90',
        variant === 'outline' && 'border border-border-strong text-primary hover:bg-surface-sunken',
        variant === 'ghost' && 'text-secondary hover:bg-surface-sunken hover:text-primary',
        variant === 'destructive' && 'bg-danger text-accent-contrast hover:bg-danger/90',
        size === 'sm' && 'px-3 py-1.5 text-sm',
        size === 'md' && 'px-4 py-2 text-base',
        size === 'lg' && 'px-6 py-3 text-lg',
        className
      )}
      {...props}
    />
  );
}
