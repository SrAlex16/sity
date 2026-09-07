import { useState, useEffect, useRef, useCallback } from 'react';

export interface Achievement {
  slug: string;
  category: string;
  name: string;
  description: string;
  unlocked: boolean;
  unlocked_at: string | null;
}

export interface AchievementsData {
  achievements: Achievement[];
  unlocked_count: number;
  total_count: number;
}

const POLL_MS = 30_000;

export function useAchievements(userId?: number) {
  const [data, setData] = useState<AchievementsData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [notifQueue, setNotifQueue] = useState<Achievement[]>([]);
  const [notification, setNotification] = useState<Achievement | null>(null);

  const prevUnlocked = useRef<Set<string> | null>(null);
  // Generation counter: incremented on every userId change so stale in-flight
  // initial fetches from the previous auth state are discarded on arrival.
  const fetchGenRef = useRef(0);
  const notifTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Advance queue when notification slot is free
  useEffect(() => {
    if (notification !== null || notifQueue.length === 0) return;
    const [first, ...rest] = notifQueue;
    setNotifQueue(rest);
    setNotification(first);
    notifTimer.current = setTimeout(() => setNotification(null), 4_000);
    return () => {
      if (notifTimer.current) clearTimeout(notifTimer.current);
    };
  }, [notification, notifQueue]);

  const fetchData = useCallback(async (initial: boolean, gen?: number) => {
    if (initial) setIsLoading(true);
    try {
      const res = await fetch('/achievements');
      if (!res.ok) return;
      // Discard result if a newer initial fetch has since started (userId changed
      // while this fetch was still in-flight).
      if (initial && gen !== undefined && gen !== fetchGenRef.current) return;
      const fresh = await res.json() as AchievementsData;
      setData(fresh);

      const freshSet = new Set(fresh.achievements.filter(a => a.unlocked).map(a => a.slug));

      if (!initial && prevUnlocked.current !== null) {
        const newOnes = fresh.achievements.filter(
          a => a.unlocked && !prevUnlocked.current!.has(a.slug)
        );
        if (newOnes.length > 0) {
          setNotifQueue(q => [...q, ...newOnes]);
        }
      }

      prevUnlocked.current = freshSet;
    } finally {
      if (initial) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    // Reset baseline on every auth change so poll fetches after login never
    // compare against the guest-state empty set.
    prevUnlocked.current = null;
    const gen = ++fetchGenRef.current;
    void fetchData(true, gen);
    const timer = setInterval(() => void fetchData(false), POLL_MS);
    const onEvent = () => void fetchData(false);
    window.addEventListener('sity:achievement-unlocked', onEvent);
    return () => {
      clearInterval(timer);
      window.removeEventListener('sity:achievement-unlocked', onEvent);
    };
  }, [fetchData, userId]);

  const dismissNotification = useCallback(() => {
    if (notifTimer.current) clearTimeout(notifTimer.current);
    setNotification(null);
  }, []);

  return { data, isLoading, notification, dismissNotification };
}
