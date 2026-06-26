import SwiftUI
import UIKit

enum AppTheme {
    static let background = Color(uiColor: .systemGroupedBackground)
    static let card = Color(uiColor: .secondarySystemGroupedBackground)
    static let surface = Color(uiColor: .systemBackground)
    static let surfaceElevated = Color(uiColor: .secondarySystemBackground)
    static let text = Color(uiColor: .label)
    static let textSecondary = Color(uiColor: .secondaryLabel)
    static let textMuted = Color(uiColor: .tertiaryLabel)
    static let border = Color(uiColor: .separator).opacity(0.42)
    static let borderSoft = Color(uiColor: .separator).opacity(0.2)
    static let bubble = Color(uiColor: .tertiarySystemFill)
    static let disabled = Color(uiColor: .systemGray5)
    static let primaryAction = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark ? .white : .black
    })
    static let onPrimaryAction = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark ? .black : .white
    })
    static let green = Color(uiColor: .systemGreen)
    static let red = Color(uiColor: .systemRed)
    static let orangeBackground = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 72 / 255, green: 49 / 255, blue: 27 / 255, alpha: 1)
            : UIColor(red: 250 / 255, green: 241 / 255, blue: 232 / 255, alpha: 1)
    })
    static let orangeText = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 255 / 255, green: 189 / 255, blue: 122 / 255, alpha: 1)
            : UIColor(red: 107 / 255, green: 74 / 255, blue: 46 / 255, alpha: 1)
    })

    enum Spacing {
        static let xxs: CGFloat = 4
        static let xs: CGFloat = 8
        static let sm: CGFloat = 12
        static let md: CGFloat = 16
        static let lg: CGFloat = 20
        static let xl: CGFloat = 24
        static let xxl: CGFloat = 32
    }

    enum Radius {
        static let chip: CGFloat = 14
        static let composer: CGFloat = 24
        static let card: CGFloat = 24
        static let sheet: CGFloat = 28
    }

    enum Typography {
        static let nav = Font.headline.weight(.semibold)
        static let title = Font.largeTitle.weight(.bold)
        static let cardTitle = Font.title2.weight(.bold)
        static let body = Font.body
        static let caption = Font.caption
    }

    enum Icon {
        static let toolbar = Font.system(size: 20, weight: .semibold)
        static let row = Font.system(size: 17, weight: .semibold)
    }

    enum TouchTarget {
        static let minimum: CGFloat = 44
    }
}

extension View {
    func appScreenBackground() -> some View {
        background(AppTheme.background.ignoresSafeArea())
    }

    func appMinimumTouchTarget() -> some View {
        frame(minWidth: AppTheme.TouchTarget.minimum, minHeight: AppTheme.TouchTarget.minimum)
            .contentShape(Rectangle())
    }
}

enum AppHaptics {
    @MainActor
    static func selection() {
        UISelectionFeedbackGenerator().selectionChanged()
    }

    @MainActor
    static func success() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }

    @MainActor
    static func warning() {
        UINotificationFeedbackGenerator().notificationOccurred(.warning)
    }
}
