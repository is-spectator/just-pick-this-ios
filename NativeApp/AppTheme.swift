import SwiftUI

enum AppTheme {
    static let background = Color(red: 250 / 255, green: 250 / 255, blue: 250 / 255)
    static let card = Color.white
    static let text = Color(red: 17 / 255, green: 17 / 255, blue: 17 / 255)
    static let textSecondary = Color(red: 95 / 255, green: 95 / 255, blue: 95 / 255)
    static let textMuted = Color(red: 154 / 255, green: 154 / 255, blue: 154 / 255)
    static let border = Color(red: 236 / 255, green: 236 / 255, blue: 236 / 255)
    static let borderSoft = Color(red: 241 / 255, green: 241 / 255, blue: 241 / 255)
    static let bubble = Color(red: 240 / 255, green: 240 / 255, blue: 238 / 255)
    static let disabled = Color(red: 229 / 255, green: 229 / 255, blue: 229 / 255)
    static let green = Color(red: 31 / 255, green: 138 / 255, blue: 76 / 255)
    static let red = Color(red: 226 / 255, green: 48 / 255, blue: 58 / 255)
    static let orangeBackground = Color(red: 250 / 255, green: 241 / 255, blue: 232 / 255)
    static let orangeText = Color(red: 107 / 255, green: 74 / 255, blue: 46 / 255)
}

extension View {
    func appScreenBackground() -> some View {
        background(AppTheme.background.ignoresSafeArea())
    }
}
