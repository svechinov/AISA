import SetupRequiredGate from "@/components/SetupRequiredGate";
import AiBizOsHumanUI from "@/pages/AiBizOsHumanUI";

export default function App() {
  return (
    <SetupRequiredGate>
      <AiBizOsHumanUI />
    </SetupRequiredGate>
  );
}
