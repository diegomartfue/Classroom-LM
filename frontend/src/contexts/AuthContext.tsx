/**
 * ============================================================================
 * AUTHENTICATION CONTEXT - LearnAI Platform
 * ============================================================================
 * 
 * This context manages user authentication state throughout the application.
 * It provides login/logout functionality and role-based access control.
 * 
 * ARCHITECTURE:
 * - Uses React Context API for global state
 * - Persists session to localStorage
 * - Supports role switching for demo purposes
 * 
 * USAGE:
 * ```tsx
 * const { user, login, logout, isProfessor, isStudent } = useAuth();
 * ```
 * 
 * TO CONNECT TO REAL BACKEND:
 * 1. Replace mock login with API call
 * 2. Add token management (JWT)
 * 3. Implement refresh token logic
 * 
 * ============================================================================
 */

import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import type { User, UserRole } from '@/types';
import { mockUsers, mockProfessors, mockStudents } from '@/data/mockData';

// =============================================================================
// TYPES
// =============================================================================

interface AuthContextType {
  // State
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  
  // Role checks
  isProfessor: boolean;
  isStudent: boolean;
  
  // Actions
  login: (email: string, password: string, role: UserRole) => Promise<void>;
  logout: () => void;
  switchRole: (role: UserRole) => void; // For demo purposes
}

// =============================================================================
// CONTEXT CREATION
// =============================================================================

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// =============================================================================
// PROVIDER COMPONENT
// =============================================================================

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Load session from localStorage on mount
  useEffect(() => {
    const storedUser = localStorage.getItem('learnai_user');
    if (storedUser) {
      try {
        const parsed = JSON.parse(storedUser);
        // Convert date strings back to Date objects
        parsed.createdAt = new Date(parsed.createdAt);
        parsed.lastLoginAt = new Date(parsed.lastLoginAt);
        setUser(parsed);
      } catch (e) {
        console.error('Failed to parse stored user:', e);
        localStorage.removeItem('learnai_user');
      }
    }
    setIsLoading(false);
  }, []);

  // Persist session to localStorage
  useEffect(() => {
    if (user) {
      localStorage.setItem('learnai_user', JSON.stringify(user));
    } else {
      localStorage.removeItem('learnai_user');
    }
  }, [user]);

  /**
   * Login function - currently uses mock data
   * TO CONNECT TO REAL BACKEND: Replace with API call
   */
  const login = useCallback(async (email: string, _password: string, role: UserRole) => {
    setIsLoading(true);
    
    // Simulate API delay
    await new Promise(resolve => setTimeout(resolve, 800));
    
    // MOCK AUTHENTICATION - Replace with real API
    // For demo: any password works with known emails
    let foundUser: User | undefined;
    
    if (role === 'professor') {
      foundUser = mockProfessors.find(p => p.email === email);
    } else {
      foundUser = mockStudents.find(s => s.email === email);
    }
    
    // Also check general users if not found
    if (!foundUser) {
      foundUser = mockUsers.find(u => u.email === email && u.role === role);
    }
    
    // Demo accounts for easy testing
    if (!foundUser) {
      if (role === 'professor' && email === 'professor@demo.com') {
        foundUser = mockProfessors[0];
      } else if (role === 'student' && email === 'student@demo.com') {
        foundUser = mockStudents[0];
      }
    }
    
    if (foundUser) {
      setUser({
        ...foundUser,
        lastLoginAt: new Date(),
      });
    } else {
      throw new Error('Invalid credentials. Try: professor@demo.com or student@demo.com (any password)');
    }
    
    setIsLoading(false);
  }, []);

  /**
   * Logout function - clears session
   */
  const logout = useCallback(() => {
    setUser(null);
    localStorage.removeItem('learnai_user');
  }, []);

  /**
   * Switch role - for demo purposes only
   * Allows quick switching between professor and student views
   */
  const switchRole = useCallback((role: UserRole) => {
    if (role === 'professor') {
      setUser(mockProfessors[0]);
    } else {
      setUser(mockStudents[0]);
    }
  }, []);

  const value: AuthContextType = {
    user,
    isAuthenticated: !!user,
    isLoading,
    isProfessor: user?.role === 'professor',
    isStudent: user?.role === 'student',
    login,
    logout,
    switchRole,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

// =============================================================================
// HOOK
// =============================================================================

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
