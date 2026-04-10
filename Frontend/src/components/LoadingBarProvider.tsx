import {
  ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

type StopLoading = () => void;

type LoadingBarContextValue = {
  startLoading: () => StopLoading;
};

const LoadingBarContext = createContext<LoadingBarContextValue | null>(null);

type LoadingBarProviderProps = {
  children: ReactNode;
};

const LoadingBarProvider = ({ children }: LoadingBarProviderProps) => {
  const [pendingCount, setPendingCount] = useState(0);
  const [visible, setVisible] = useState(false);
  const [progress, setProgress] = useState(0);

  const startLoading = useCallback(() => {
    let finished = false;
    setPendingCount((count) => count + 1);

    return () => {
      if (finished) return;
      finished = true;
      setPendingCount((count) => Math.max(0, count - 1));
    };
  }, []);

  useEffect(() => {
    if (pendingCount > 0) {
      setVisible(true);
      setProgress((value) => (value > 0 ? value : 10));

      const timer = window.setInterval(() => {
        setProgress((value) => {
          if (value >= 92) return value;
          const nextStep = value + Math.max(3, (94 - value) * 0.1);
          return Math.min(92, nextStep);
        });
      }, 110);

      return () => {
        window.clearInterval(timer);
      };
    }

    if (!visible) return;

    setProgress(100);
    const timer = window.setTimeout(() => {
      setVisible(false);
      setProgress(0);
    }, 260);

    return () => {
      window.clearTimeout(timer);
    };
  }, [pendingCount, visible]);

  const value = useMemo(
    () => ({
      startLoading,
    }),
    [startLoading]
  );

  return (
    <LoadingBarContext.Provider value={value}>
      <div className={visible ? "legacy-global-loader legacy-global-loader--visible" : "legacy-global-loader"}>
        <div className="legacy-global-loader__bar" style={{ transform: `scaleX(${progress / 100})` }} />
      </div>
      {children}
    </LoadingBarContext.Provider>
  );
};

export function useLoadingBar() {
  const context = useContext(LoadingBarContext);

  if (!context) {
    throw new Error("useLoadingBar must be used within LoadingBarProvider.");
  }

  return context;
}

export default LoadingBarProvider;
