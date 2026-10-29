import { useState } from "react";
import SegmentedControl from "../SegmentedControl.jsx";
import MemberClasses from "./MemberClasses.jsx";
import MemberPrivateTraining from "./MemberPrivateTraining.jsx";
import MyBookings from "./MyBookings.jsx";

// User story: "As a member, I want to browse and book available classes or PT
// sessions directly through the app, so that I can reserve my spot without
// contacting the front desk."
//
// Group classes, the coaches and their private training, and the member's
// own bookings - each tab loads (and keeps itself up to date) on its own.
export default function MemberBooking() {
  const [tab, setTab] = useState("classes");
  return (
    <div>
      <div style={styles.tabs}>
        <SegmentedControl
          ariaLabel="Booking"
          options={[
            { value: "classes", label: "Classes" },
            { value: "pt", label: "Coaches & PT" },
            { value: "mine", label: "My bookings" },
          ]}
          value={tab}
          onChange={setTab}
        />
      </div>
      {tab === "classes" && <MemberClasses />}
      {tab === "pt" && <MemberPrivateTraining />}
      {tab === "mine" && <MyBookings />}
    </div>
  );
}

const styles = {
  tabs: { marginBottom: 12 },
};
