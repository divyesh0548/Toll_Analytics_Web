import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { LogOut, Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { useTheme } from '@/components/theme-provider'
import { useAuth } from '@/components/auth-provider'
import { cn } from '@/lib/utils'

export function Navbar() {
  const { theme, toggleTheme } = useTheme()
  const { user, isSiteAdmin, logout } = useAuth()
  const navigate = useNavigate()
  const [confirmLogout, setConfirmLogout] = useState(false)

  const navItems = isSiteAdmin
    ? [{ to: '/admin/users', label: 'Users' }]
    : [{ to: '/portfolio', label: 'Portfolio' }]

  function handleConfirmLogout() {
    logout()
    setConfirmLogout(false)
    navigate('/', { replace: true })
  }

  return (
    <>
      <header className="sticky top-0 z-40 w-full border-b border-border/80 bg-background/85 backdrop-blur-md">
        <div className="content-shell flex h-14 items-center justify-between gap-4">
          <div className="flex items-center gap-6">
            <Link
              to={isSiteAdmin ? '/admin/users' : '/portfolio'}
              className="text-subheader text-primary"
            >
              Toll Analytics
            </Link>
            <nav className="hidden items-center gap-1 sm:flex">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    cn(
                      'rounded-sm px-3 py-1.5 text-body transition-colors',
                      isActive
                        ? 'bg-accent text-accent-foreground'
                        : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
                    )
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>

          <div className="flex items-center gap-2">
            {user && (
              <span className="hidden text-small capitalize text-muted-foreground sm:inline">
                {user.role}
              </span>
            )}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="transition-colors hover:bg-primary/15 hover:text-primary"
              onClick={toggleTheme}
              aria-label="Toggle dark mode"
            >
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="transition-colors hover:border-primary/40 hover:bg-primary/15 hover:text-primary"
              onClick={() => setConfirmLogout(true)}
            >
              <LogOut className="h-4 w-4" />
              Logout
            </Button>
          </div>
        </div>
      </header>

      <Dialog
        open={confirmLogout}
        onClose={() => setConfirmLogout(false)}
        title="Confirm logout"
        description="Are you sure you want to log out of Toll Analytics?"
        className="max-w-sm"
      >
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => setConfirmLogout(false)}>
            Stay signed in
          </Button>
          <Button type="button" onClick={handleConfirmLogout}>
            Log out
          </Button>
        </div>
      </Dialog>
    </>
  )
}
